"""The Campaign API's run-control routes in process (real routes, SQLite, a Temporal recorder):
a campaign is approved, retried, or given a new budget only from the state that allows it, by
the role that may, and each accepted request signals its run once."""

import uuid

import pytest
from ace_engine import db
from ace_engine.settings import APPROVE_SIGNAL, RAISE_BUDGET_SIGNAL, RETRY_SIGNAL
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.app import StubTemporal
from tests.support.campaigns import add_campaign, add_usage, campaign_status
from tests.support.dag import APPROVER, OWNER

# Every status a campaign can be in when a request for it arrives.
ALL_STATUSES = [
    db.DRAFTING,
    db.AWAITING_APPROVAL,
    db.SENDING,
    db.SENT,
    db.FAILED,
    db.RETRYING,
    db.FINISHED,
    db.BUDGET_PAUSED,
]


def as_user(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {email}"}


def signals(temporal: StubTemporal, campaign_id: uuid.UUID) -> list[str]:
    return [
        name
        for workflow_id, name, _ in temporal.signals
        if workflow_id == f"campaign-{campaign_id}"
    ]


def test_an_approver_approves_a_waiting_campaign_and_the_run_is_signalled_once(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.AWAITING_APPROVAL)

    response = app_client.post(f"/campaigns/{campaign_id}/approve", headers=as_user(APPROVER))

    assert response.status_code == 202, response.text
    assert response.json()["status"] == db.SENDING
    assert signals(temporal, campaign_id) == [APPROVE_SIGNAL]


@pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != db.AWAITING_APPROVAL])
def test_a_campaign_not_waiting_for_approval_is_never_approved(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal, status: str
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=status)

    response = app_client.post(f"/campaigns/{campaign_id}/approve", headers=as_user(APPROVER))

    assert response.status_code == 409, response.text
    assert campaign_status(sqlite_engine, campaign_id) == status
    assert signals(temporal, campaign_id) == []


def test_approving_twice_signals_the_run_once(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.AWAITING_APPROVAL)
    headers = as_user(APPROVER)

    first = app_client.post(f"/campaigns/{campaign_id}/approve", headers=headers)
    second = app_client.post(f"/campaigns/{campaign_id}/approve", headers=headers)

    assert (first.status_code, second.status_code) == (202, 409)
    assert signals(temporal, campaign_id) == [APPROVE_SIGNAL]


def test_approving_an_unknown_campaign_is_404(
    app_client: TestClient, temporal: StubTemporal
) -> None:
    response = app_client.post(f"/campaigns/{uuid.uuid4()}/approve", headers=as_user(APPROVER))

    assert response.status_code == 404
    assert temporal.signals == []


def test_a_failed_run_retries_its_step_and_the_run_is_signalled(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(
        sqlite_engine, status=db.FAILED, failure_reason="step 'writer' failed after 2 attempts"
    )

    response = app_client.post(f"/campaigns/{campaign_id}/retry", headers=as_user(OWNER))

    assert response.status_code == 202, response.text
    assert response.json()["status"] == db.RETRYING
    assert response.json()["failure_reason"] is None
    assert signals(temporal, campaign_id) == [RETRY_SIGNAL]


@pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != db.FAILED])
def test_retry_is_refused_unless_the_run_failed(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal, status: str
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=status)

    response = app_client.post(f"/campaigns/{campaign_id}/retry", headers=as_user(OWNER))

    assert response.status_code == 409, response.text
    assert campaign_status(sqlite_engine, campaign_id) == status
    assert signals(temporal, campaign_id) == []


def test_an_approver_cannot_retry_and_an_unknown_campaign_is_404(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.FAILED)

    by_approver = app_client.post(f"/campaigns/{campaign_id}/retry", headers=as_user(APPROVER))
    unknown = app_client.post(f"/campaigns/{uuid.uuid4()}/retry", headers=as_user(OWNER))

    assert by_approver.status_code == 403
    assert unknown.status_code == 404
    assert campaign_status(sqlite_engine, campaign_id) == db.FAILED
    assert temporal.signals == []


def test_the_owner_raises_the_budget_of_a_paused_run_and_it_is_signalled(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.BUDGET_PAUSED, budget_micros=10_000)
    add_usage(sqlite_engine, campaign_id, "first", cost_micros=21_000)

    response = app_client.post(
        f"/campaigns/{campaign_id}/budget", json={"budget_usd": 1}, headers=as_user(OWNER)
    )

    assert response.status_code == 200, response.text
    assert response.json()["budget_usd"] == pytest.approx(1)
    assert response.json()["status"] == db.DRAFTING
    assert signals(temporal, campaign_id) == [RAISE_BUDGET_SIGNAL]


def test_a_budget_below_what_was_spent_is_refused_and_nothing_changes(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.BUDGET_PAUSED, budget_micros=10_000)
    add_usage(sqlite_engine, campaign_id, "first", cost_micros=21_000)

    response = app_client.post(
        f"/campaigns/{campaign_id}/budget", json={"budget_usd": 0.02}, headers=as_user(OWNER)
    )

    assert response.status_code == 422, response.text
    assert "spent" in response.text
    assert campaign_status(sqlite_engine, campaign_id) == db.BUDGET_PAUSED
    assert signals(temporal, campaign_id) == []


def test_only_an_owner_raises_the_budget(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.BUDGET_PAUSED, budget_micros=10_000)

    response = app_client.post(
        f"/campaigns/{campaign_id}/budget", json={"budget_usd": 1}, headers=as_user(APPROVER)
    )

    assert response.status_code == 403, response.text
    assert campaign_status(sqlite_engine, campaign_id) == db.BUDGET_PAUSED
    assert temporal.signals == []


@pytest.mark.parametrize("status", [db.SENT, db.FINISHED])
def test_the_budget_of_a_run_that_has_ended_is_left_alone(
    app_client: TestClient, sqlite_engine: Engine, temporal: StubTemporal, status: str
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=status, budget_micros=10_000)

    response = app_client.post(
        f"/campaigns/{campaign_id}/budget", json={"budget_usd": 1}, headers=as_user(OWNER)
    )

    assert response.status_code == 409, response.text
    assert temporal.signals == []


@pytest.mark.parametrize("budget", [0, -1, "lots"])
def test_a_campaign_is_not_created_with_a_budget_that_is_not_a_positive_amount(
    app_client: TestClient, temporal: StubTemporal, budget: float | str
) -> None:
    response = app_client.post(
        "/campaigns", json={"report": "a report", "budget_usd": budget}, headers=as_user(OWNER)
    )

    assert response.status_code == 422, response.text
    assert temporal.started == []
