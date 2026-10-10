"""Seam 1 at fast depth: sign-in and roles. Every request carries a demo user's real
token from Dex; the Campaign API reads the team and the roles from its claims.

Owners create and run campaigns, approvers approve, viewers read, and nobody approves a
campaign they created.
"""

from typing import Any

import httpx
import pytest

from tests.api.conftest import SignIn
from tests.api.helpers import (
    AWAITING,
    DRAFT_APPROVE_PUBLISH,
    create,
    read_events,
    save_workflow,
    settle,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

LEAD = "dg-lead@demo.example"
TEAM_OWNER = {
    "demand-gen": "dg-owner@demo.example",
    "product-marketing": "pm-owner@demo.example",
}

# Every demo user, their team and roles as the token should carry them, and the status
# each action gets. "approve" is on a campaign their team's owner created and that is
# waiting for approval. "save_workflow" saves a new workflow version; "read_workflow" reads
# one their team's owner saved.
# Every role in a team reads every campaign view and every workflow.
READS_OK = {
    "list": 200,
    "read": 200,
    "events": 200,
    "preview": 200,
    "activity": 200,
    "read_workflow": 200,
}
ROLE_TABLE: dict[str, tuple[str, list[str], dict[str, int]]] = {
    "dg-owner@demo.example": (
        "demand-gen",
        ["owner"],
        {**READS_OK, "create": 201, "save_workflow": 201, "approve": 403},
    ),
    "dg-approver@demo.example": (
        "demand-gen",
        ["approver"],
        {**READS_OK, "create": 403, "save_workflow": 403, "approve": 202},
    ),
    "dg-viewer@demo.example": (
        "demand-gen",
        ["viewer"],
        {**READS_OK, "create": 403, "save_workflow": 403, "approve": 403},
    ),
    "dg-lead@demo.example": (
        "demand-gen",
        ["approver", "owner"],
        {**READS_OK, "create": 201, "save_workflow": 201, "approve": 202},
    ),
    "pm-owner@demo.example": (
        "product-marketing",
        ["owner"],
        {**READS_OK, "create": 201, "save_workflow": 201, "approve": 403},
    ),
    "pm-approver@demo.example": (
        "product-marketing",
        ["approver"],
        {**READS_OK, "create": 403, "save_workflow": 403, "approve": 202},
    ),
    "pm-viewer@demo.example": (
        "product-marketing",
        ["viewer"],
        {**READS_OK, "create": 403, "save_workflow": 403, "approve": 403},
    ),
}
ACTIONS = [*READS_OK, "create", "save_workflow", "approve"]
CASES = [(email, action) for email in ROLE_TABLE for action in ACTIONS]


def _waiting_campaign(sign_in: SignIn, team: str) -> str:
    owner = sign_in(TEAM_OWNER[team])
    campaign_id: str = create(owner)["id"]
    assert settle(owner, campaign_id)["status"] == AWAITING
    return campaign_id


def _saved_workflow(sign_in: SignIn, team: str) -> str:
    name = workflow_name("access")
    save_workflow(sign_in(TEAM_OWNER[team]), name, DRAFT_APPROVE_PUBLISH)
    return name


def _events_status(client: httpx.Client, campaign_id: str) -> int:
    with client.stream("GET", f"/campaigns/{campaign_id}/events") as response:
        response.read()
        return response.status_code


def _act(client: httpx.Client, action: str, campaign_id: str | None) -> int:
    if action == "save_workflow":
        url = f"/workflows/{workflow_name('access')}/versions"
        return client.post(url, json=DRAFT_APPROVE_PUBLISH).status_code
    if action == "read_workflow":
        return client.get(f"/workflows/{campaign_id}/versions/1").status_code
    if action == "list":
        return client.get("/campaigns").status_code
    if action == "create":
        return client.post("/campaigns", json={"report": "Volt Typhoon"}).status_code
    if action == "read":
        return client.get(f"/campaigns/{campaign_id}").status_code
    if action == "events":
        return _events_status(client, campaign_id or "")
    if action in {"preview", "activity"}:
        return client.get(f"/campaigns/{campaign_id}/{action}").status_code
    return client.post(f"/campaigns/{campaign_id}/approve").status_code


def test_every_demo_user_signs_in_with_team_and_roles(sign_in: SignIn) -> None:
    for email, (team, roles, _) in ROLE_TABLE.items():
        response = sign_in(email).get("/me")

        assert response.status_code == 200, response.text
        me = response.json()
        assert (me["email"], me["team"], me["roles"]) == (email, team, roles)
        assert me["subject"]


@pytest.mark.parametrize(("email", "action"), CASES)
def test_role_table(stack: Stack, sign_in: SignIn, email: str, action: str) -> None:
    stack.agent.script([])
    team, _, expected = ROLE_TABLE[email]
    needs_campaign = action in {"read", "events", "preview", "activity", "approve"}
    campaign_id = _waiting_campaign(sign_in, team) if needs_campaign else None
    if action == "read_workflow":
        campaign_id = _saved_workflow(sign_in, team)

    status = _act(sign_in(email), action, campaign_id)

    assert status == expected[action]


def test_owner_cannot_approve_their_own_campaign(stack: Stack, sign_in: SignIn) -> None:
    stack.agent.script([])
    lead = sign_in(LEAD)
    campaign_id = create(lead)["id"]
    assert settle(lead, campaign_id)["status"] == AWAITING

    refused = lead.post(f"/campaigns/{campaign_id}/approve")

    assert refused.status_code == 403
    assert "own campaign" in refused.json()["detail"]
    assert lead.get(f"/campaigns/{campaign_id}").json()["status"] == AWAITING
    approved = sign_in("dg-approver@demo.example").post(f"/campaigns/{campaign_id}/approve")
    assert approved.status_code == 202, approved.text
    until_status(lead, campaign_id, "sent")


def test_created_campaign_shows_in_the_list(api: httpx.Client) -> None:
    created = create(api)

    listed: list[dict[str, Any]] = api.get("/campaigns").json()

    assert created["id"] in [c["id"] for c in listed]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic dXNlcjpwYXNz"}],
    ids=["no token", "garbage token", "not a bearer token"],
)
def test_requests_without_a_valid_token_get_401(
    stack: Stack, api: httpx.Client, headers: dict[str, str]
) -> None:
    campaign_id = create(api)["id"]
    requests = [
        ("GET", "/campaigns"),
        ("POST", "/campaigns"),
        ("GET", f"/campaigns/{campaign_id}"),
        ("GET", f"/campaigns/{campaign_id}/events"),
        ("GET", f"/campaigns/{campaign_id}/preview"),
        ("GET", f"/campaigns/{campaign_id}/activity"),
        ("POST", f"/workflows/{workflow_name('anon')}/versions"),
        ("GET", "/workflows/any-name/versions/1"),
        ("POST", f"/campaigns/{campaign_id}/approve"),
        ("GET", "/me"),
    ]
    with httpx.Client(base_url=stack.api_url, headers=headers) as anonymous:
        for method, path in requests:
            response = anonymous.request(method, path, json={"report": "x"})

            assert response.status_code == 401, (method, path, response.text)
            assert response.headers["www-authenticate"].startswith("Bearer")


def test_preview_takes_the_token_as_a_query_parameter(stack: Stack, api: httpx.Client) -> None:
    """The browser loads the preview in an iframe, which cannot send headers either."""
    campaign_id = settle(api, create(api)["id"])["id"]
    token = stack.dex.token("dg-viewer@demo.example")

    with httpx.Client(base_url=stack.api_url, params={"access_token": token}) as browser:
        response = browser.get(f"/campaigns/{campaign_id}/preview")

    assert response.status_code == 200, response.text


def test_event_stream_takes_the_token_as_a_query_parameter(stack: Stack, api: httpx.Client) -> None:
    """A browser EventSource cannot send headers, so the stream also reads `access_token`."""
    campaign_id = create(api)["id"]
    token = stack.dex.token("dg-viewer@demo.example")

    with httpx.Client(base_url=stack.api_url, params={"access_token": token}) as browser:
        events = read_events(browser, campaign_id)

    assert events[-1]["step"] == "run"
