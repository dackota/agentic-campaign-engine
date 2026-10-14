"""Sign-in and roles on every route of the real Campaign API, in process: each demo user
gets the status their roles allow on every kind of request, and a request without a valid
token is turned away with a 401. The token's claims becoming a team and roles is proved on
a real Dex token in tests/api/test_access.py."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from ace_engine import db
from campaign_api.auth import TokenVerifier
from campaign_api.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.app import StubTemporal, StubVerifier
from tests.support.dag import DRAFT_APPROVE_PUBLISH, GOOD_DRAFT
from tests.support.seed import add_campaign
from tests.support.settings import unit_settings

WORKFLOW = "access-workflow"
# Every demo user, their team and the roles their token carries (platform/dex/config.yaml).
USERS = {
    "dg-owner@demo.example": ("demand-gen", {"owner"}),
    "dg-approver@demo.example": ("demand-gen", {"approver"}),
    "dg-viewer@demo.example": ("demand-gen", {"viewer"}),
    "dg-lead@demo.example": ("demand-gen", {"approver", "owner"}),
    "pm-owner@demo.example": ("product-marketing", {"owner"}),
    "pm-approver@demo.example": ("product-marketing", {"approver"}),
    "pm-viewer@demo.example": ("product-marketing", {"viewer"}),
    # A login that is in no team and has no role: it may do nothing.
    "nobody@demo.example": ("demand-gen", set()),
}
# What each request needs of its sender, and the status that says it was let through. Every
# role in a team reads; an owner creates; an approver approves. {id} is a campaign waiting for
# approval that someone else created, {workflow} a saved workflow.
READ, CREATE, APPROVE = "read", "create", "approve"
REQUESTS: dict[str, tuple[str, str, str, dict[str, Any] | None, int]] = {
    "list": (READ, "GET", "/campaigns", None, 200),
    "read": (READ, "GET", "/campaigns/{id}", None, 200),
    "events": (READ, "GET", "/campaigns/{id}/events", None, 200),
    "steps": (READ, "GET", "/campaigns/{id}/steps", None, 200),
    "preview": (READ, "GET", "/campaigns/{id}/preview", None, 200),
    "activity": (READ, "GET", "/campaigns/{id}/activity", None, 200),
    "dashboard": (READ, "GET", "/dashboard", None, 200),
    "alerts": (READ, "GET", "/alerts", None, 200),
    "learnings": (READ, "GET", "/learnings", None, 200),
    "workflow_names": (READ, "GET", "/workflows", None, 200),
    "read_workflow": (READ, "GET", "/workflows/{workflow}/versions/1", None, 200),
    "create": (CREATE, "POST", "/campaigns", {"report": "Volt Typhoon"}, 201),
    "save_workflow": (
        CREATE,
        "POST",
        "/workflows/{new_workflow}/versions",
        DRAFT_APPROVE_PUBLISH,
        201,
    ),
    "validate_workflow": (CREATE, "POST", "/workflows/validate", DRAFT_APPROVE_PUBLISH, 200),
    "raise_budget": (CREATE, "POST", "/campaigns/{id}/budget", {"budget_usd": 5}, 200),
    # The run has not failed, so an owner's retry is refused for that reason, not for the role.
    "retry": (CREATE, "POST", "/campaigns/{id}/retry", None, 409),
    "approve": (APPROVE, "POST", "/campaigns/{id}/approve", None, 202),
    "inbox": (APPROVE, "GET", "/inbox", None, 200),
    # An approver reaches the learning and finds there is none by that id.
    "delete_learning": (APPROVE, "DELETE", "/learnings/{id}", None, 404),
}
# The roles that may send a request of each kind.
ROLES_THAT_MAY = {
    READ: {"owner", "approver", "viewer"},
    CREATE: {"owner"},
    APPROVE: {"approver"},
}
CASES = [(email, request) for email in USERS for request in REQUESTS]
FORBIDDEN = 403


class MatrixVerifier(StubVerifier):
    """The demo users, and one login of no team and no role."""

    def __init__(self) -> None:
        super().__init__()
        self._claims["nobody@demo.example"] = {
            "sub": "nobody",
            "email": "nobody@demo.example",
            "groups": [],
        }


@pytest.fixture
def api_client(sqlite_engine: Engine, temporal: StubTemporal) -> Iterator[TestClient]:
    app = create_app(
        unit_settings(),
        engine=sqlite_engine,
        verifier=MatrixVerifier(),  # type: ignore[arg-type]
        temporal=temporal,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        yield client


def _seed(engine: Engine, team: str) -> uuid.UUID:
    campaign_id = add_campaign(engine, team=team, draft=GOOD_DRAFT)
    with Session(engine) as session, session.begin():
        db.add_event(session, campaign_id, db.RUN_STEP, db.AWAITING_APPROVAL)
        session.add(db.WorkflowVersion(name=WORKFLOW, version=1, dag=DRAFT_APPROVE_PUBLISH))
    return campaign_id


@pytest.mark.parametrize(("email", "request_name"), CASES)
def test_each_demo_user_gets_the_status_their_roles_allow(
    api_client: TestClient, sqlite_engine: Engine, email: str, request_name: str
) -> None:
    team, roles = USERS[email]
    needed, method, path, body, allowed_status = REQUESTS[request_name]
    campaign_id = _seed(sqlite_engine, team)
    url = path.format(id=campaign_id, workflow=WORKFLOW, new_workflow="a-new-workflow")

    response = api_client.request(
        method, url, json=body, headers={"Authorization": f"Bearer {email}"}
    )

    is_allowed = bool(roles & ROLES_THAT_MAY[needed])
    assert response.status_code == (allowed_status if is_allowed else FORBIDDEN), response.text


def test_a_campaign_creator_who_may_approve_still_cannot_approve_their_own(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    lead = "dg-lead@demo.example"
    created = app_client.post(
        "/campaigns", json={"report": "Volt Typhoon"}, headers={"Authorization": f"Bearer {lead}"}
    ).json()
    app_client.headers["Authorization"] = f"Bearer {lead}"
    with Session(sqlite_engine) as session, session.begin():
        session.get_one(db.Campaign, uuid.UUID(created["id"])).status = db.AWAITING_APPROVAL

    refused = app_client.post(f"/campaigns/{created['id']}/approve")
    approved = app_client.post(
        f"/campaigns/{created['id']}/approve",
        headers={"Authorization": "Bearer dg-approver@demo.example"},
    )

    assert refused.status_code == FORBIDDEN
    assert "own campaign" in refused.json()["detail"]
    assert approved.status_code == 202, approved.text
    assert [name for _, name, _ in temporal.signals] == ["approve"]
    assert app_client.get(f"/campaigns/{created['id']}").json()["status"] == db.SENDING


@pytest.fixture
def signed_out_client(sqlite_engine: Engine) -> Iterator[TestClient]:
    """The Campaign API with the real token verifier, which has no identity provider to ask:
    a token that is not even a well-formed JWT is refused before any key is fetched."""
    verifier = TokenVerifier("http://dex.invalid/dex", "ace-web")
    app = create_app(
        unit_settings(),
        engine=sqlite_engine,
        verifier=verifier,
        temporal=StubTemporal(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic dXNlcjpwYXNz"}],
    ids=["no token", "garbage token", "not a bearer token"],
)
@pytest.mark.parametrize("request_name", sorted(REQUESTS))
def test_requests_without_a_valid_token_get_401(
    signed_out_client: TestClient, sqlite_engine: Engine, request_name: str, headers: dict[str, str]
) -> None:
    campaign_id = _seed(sqlite_engine, "demand-gen")
    _, method, path, body, _ = REQUESTS[request_name]
    url = path.format(id=campaign_id, workflow=WORKFLOW, new_workflow="a-new-workflow")

    response = signed_out_client.request(method, url, json=body, headers=headers)

    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_me_without_a_valid_token_gets_401(signed_out_client: TestClient) -> None:
    response = signed_out_client.get("/me", headers={"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("route", ["preview", "events"])
def test_browser_routes_take_the_token_as_a_query_parameter(
    app_client: TestClient, sqlite_engine: Engine, route: str
) -> None:
    """The browser loads the preview in an iframe and follows a run with an EventSource: neither
    can send headers."""
    campaign_id = _seed(sqlite_engine, "demand-gen")
    url = f"/campaigns/{campaign_id}/{route}"

    by_query = app_client.get(url, params={"access_token": "dg-viewer@demo.example"})
    refused = app_client.get(url, params={"access_token": "not-a-user"})
    header_first = app_client.get(
        url,
        params={"access_token": "not-a-user"},
        headers={"Authorization": "Bearer dg-viewer@demo.example"},
    )

    assert by_query.status_code == 200, by_query.text
    assert refused.status_code == 401
    assert header_first.status_code == 200, header_first.text
