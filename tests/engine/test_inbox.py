"""The approval inbox on SQLite: what an approver sees of the campaigns waiting for approval,
how decisions settle a campaign, and how a rejected asset is redone. The team filter is
row-level security, which SQLite cannot show: see test_inbox_teams.py."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from ace_engine import db
from ace_engine.settings import APPROVE_SIGNAL
from campaign_api import inbox
from campaign_api.auth import User
from campaign_worker.activities import RedoJob
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.exceptions import ApplicationError

from tests.support.app import StubTemporal, StubVerifier
from tests.support.dag import APPROVER, OWNER, REPORT
from tests.support.scripted_outputs import scripted_output
from tests.support.scripted_worker import ScriptedWorker, run_step, scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

LEAD = "dg-lead@demo.example"
AS_APPROVER = {"Authorization": f"Bearer {APPROVER}"}
ASSETS = ("landing_page", "social", "one_pager", "email_writer", "design")
PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
REDONE_PAGE = {**PAGE, "body": "Calmer words"}
FIXED_PAGE = {**PAGE, "body": "Calm and checked"}
FIX: dict[str, Any] = {
    "verdict": "fix",
    "issues": [{"check": "banned_claim", "detail": "100% protection is a banned claim"}],
}
PASS = {"verdict": "pass", "issues": []}
COMMENT = "Drop the hype"


def user(email: str) -> User:
    return StubVerifier().verify(email)


def all_outputs() -> dict[str, Any]:
    return {step: scripted_output(step) for step in ASSETS}


def waiting(
    engine: Engine,
    *,
    created_by: str = OWNER,
    status: str = db.AWAITING_APPROVAL,
    outputs: dict[str, Any] | None = None,
) -> uuid.UUID:
    """A campaign of the default workflow, its five assets written, in `status`."""
    seed = CampaignSeed(
        created_by=created_by, status=status, outputs=all_outputs() if outputs is None else outputs
    )
    return seed_campaign(engine, seed)


def flag(engine: Engine, campaign: uuid.UUID, step: str, issues: list[dict[str, str]]) -> None:
    with Session(engine) as session, session.begin():
        db.add_event(session, campaign, step, db.FLAGGED, json.dumps(issues))


def items_of(engine: Engine, email: str = APPROVER) -> list[inbox.AssetOut]:
    return inbox._inbox(engine, user(email))


def test_an_approver_sees_the_five_waiting_assets_of_a_campaign(sqlite_engine: Engine) -> None:
    campaign = waiting(sqlite_engine)

    items = items_of(sqlite_engine)

    assert {i.step for i in items} == set(ASSETS)
    assert {i.campaign_id for i in items} == {campaign}
    assert {i.team for i in items} == {"demand-gen"}


def test_the_inbox_leaves_out_a_campaign_still_drafting_and_the_approvers_own(
    sqlite_engine: Engine,
) -> None:
    drafting = waiting(sqlite_engine, status=db.DRAFTING)
    own = waiting(sqlite_engine, created_by=LEAD)

    assert items_of(sqlite_engine, LEAD) == []
    assert {i.campaign_id for i in items_of(sqlite_engine, APPROVER)} == {own}
    assert drafting not in {i.campaign_id for i in items_of(sqlite_engine, APPROVER)}


def test_each_asset_carries_its_preview_path_and_the_reviewers_flags(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    campaign = waiting(sqlite_engine, outputs={"landing_page": PAGE})
    flag(sqlite_engine, campaign, "landing_page", FIX["issues"])

    [item] = items_of(sqlite_engine)

    assert item.step == "landing_page"
    assert item.output == PAGE
    assert [f.check for f in item.flags] == ["banned_claim"]
    assert "banned claim" in item.flags[0].detail
    assert item.preview_url == f"/campaigns/{campaign}/preview/landing-page"
    preview = app_client.get(item.preview_url or "", headers=AS_APPROVER)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    assert PAGE["headline"] in preview.text


@pytest.mark.parametrize(
    ("step", "preview"),
    [
        ("landing_page", "preview/landing-page"),
        ("social", "preview/social"),
        ("design", "preview/cards"),
        ("one_pager", "preview/graphic"),
        ("email_writer", "preview"),
    ],
)
def test_each_asset_previews_through_the_route_that_renders_it(
    sqlite_engine: Engine, step: str, preview: str
) -> None:
    campaign = waiting(sqlite_engine)

    [item] = [i for i in items_of(sqlite_engine) if i.step == step]

    assert item.preview_url == f"/campaigns/{campaign}/{preview}"


def test_the_inbox_keeps_each_waiting_campaigns_assets_flags_and_approvals_apart(
    sqlite_engine: Engine,
) -> None:
    first, second = waiting(sqlite_engine), waiting(sqlite_engine)
    flag(sqlite_engine, first, "social", FIX["issues"])
    with Session(sqlite_engine) as session, session.begin():
        session.add(
            db.AssetApproval(campaign_id=first, step="social", approved_by="someone", comment="")
        )

    items = items_of(sqlite_engine)

    by_campaign = {c: [i for i in items if i.campaign_id == c] for c in (first, second)}
    assert {i.step for i in by_campaign[first]} == set(ASSETS) - {"social"}
    assert {i.step for i in by_campaign[second]} == set(ASSETS)
    assert all(i.flags == [] for i in by_campaign[second])
    assert all(i.output == all_outputs()[i.step] for i in by_campaign[second])


def test_approving_every_asset_one_by_one_sends_the_campaign_on_the_last(
    sqlite_engine: Engine, app_client: TestClient, temporal: StubTemporal
) -> None:
    campaign = waiting(sqlite_engine)

    def approve(asset: str) -> str:
        response = app_client.post(
            f"/campaigns/{campaign}/assets/{asset}/approve",
            json={"comment": ""},
            headers=AS_APPROVER,
        )
        assert response.status_code == 200, response.text
        return str(response.json()["campaign_status"])

    statuses = [approve(asset) for asset in ASSETS]

    assert statuses == [db.AWAITING_APPROVAL] * 4 + [db.SENDING]
    assert temporal.signals == [(f"campaign-{campaign}", APPROVE_SIGNAL, [])]
    assert app_client.get(f"/campaigns/{campaign}", headers=AS_APPROVER).json()["status"] == (
        db.SENDING
    )


def test_a_rejection_sends_the_asset_back_with_the_comment_and_signals_the_run(
    sqlite_engine: Engine, app_client: TestClient, temporal: StubTemporal
) -> None:
    campaign = waiting(sqlite_engine)

    rejected = app_client.post(
        f"/campaigns/{campaign}/assets/landing_page/reject",
        json={"comment": COMMENT},
        headers=AS_APPROVER,
    )

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["decision"] == "rejected"
    assert rejected.json()["campaign_status"] == db.DRAFTING
    assert temporal.signals == [(f"campaign-{campaign}", "reject_asset", ["landing_page", COMMENT])]
    events = db.events_after(sqlite_engine, campaign, 0)
    assert [(e.step, e.status, e.reason) for e in events if e.status == db.ASSET_REJECTED] == [
        ("landing_page", db.ASSET_REJECTED, COMMENT)
    ]
    assert db.rejection_count(sqlite_engine, campaign, "landing_page") == 1


class Redo:
    """A campaign whose landing page was written once, then sent back by an approver."""

    def __init__(
        self,
        engine: Engine,
        first_replies: list[dict[str, Any]],
        budget_micros: int | None = None,
    ) -> None:
        self.engine = engine
        self.campaign = seed_campaign(
            engine, CampaignSeed(dag=LANDING_PAGE_DAG, budget_micros=budget_micros)
        )
        self.worker: ScriptedWorker = scripted_worker(engine)
        self.worker.agent.script([json.dumps(r) for r in first_replies])
        self.first = run_step(self.worker, self.campaign, "landing_page", REPORT, 2)
        self.sent_before = len(self.worker.messages_sent())

    def redo(self, replies: list[dict[str, Any]], review_rounds: int = 2) -> dict[str, Any]:
        self.worker.agent.script([json.dumps(r) for r in replies])
        job = RedoJob(str(self.campaign), REPORT, "landing_page", COMMENT, {}, review_rounds)
        result: dict[str, Any] = asyncio.run(self.worker.activities.redo_asset(job))
        return result

    def sent_since(self) -> list[tuple[str, str | None]]:
        return self.worker.messages_sent()[self.sent_before :]


LANDING_PAGE_DAG = {
    "steps": [{"id": "landing_page", "kind": "agent", "review_rounds": 2}],
    "edges": [],
}


def test_a_redone_asset_goes_through_the_brand_reviewer_again(sqlite_engine: Engine) -> None:
    redo = Redo(sqlite_engine, [PAGE, FIX, PAGE, FIX, PAGE, FIX])
    with Session(sqlite_engine) as session:
        assert [f.step for f in db.review_flags(session, redo.campaign)] == ["landing_page"]

    # The redo, the reviewer's fix, the writer's fix, and the reviewer's pass.
    result = redo.redo([REDONE_PAGE, FIX, FIXED_PAGE, PASS])

    assert result["output"] == FIXED_PAGE
    with Session(sqlite_engine) as session:
        assert db.review_flags(session, redo.campaign) == []
    assert len(redo.sent_since()) == 4
    [item] = items_of(sqlite_engine)  # the inbox shows the redone page, flags cleared
    assert (item.output, item.flags) == (FIXED_PAGE, [])


def test_a_redo_goes_to_the_writers_own_session_with_message_ids_of_its_own(
    sqlite_engine: Engine,
) -> None:
    redo = Redo(sqlite_engine, [PAGE, PASS])

    redo.redo([REDONE_PAGE], review_rounds=0)

    [(message_id, session)] = redo.sent_since()
    assert session == redo.first["writer_sessions"][0]
    assert message_id not in [m for m, _ in redo.worker.messages_sent()[: redo.sent_before]]


def test_a_redo_stops_at_a_spent_budget_without_calling_the_agent(sqlite_engine: Engine) -> None:
    redo = Redo(sqlite_engine, [PAGE, PASS], budget_micros=10_000)
    with Session(sqlite_engine) as session, session.begin():
        session.add(
            db.StepUsage(
                campaign_id=redo.campaign,
                step="earlier",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_micros=10_500,
            )
        )

    with pytest.raises(ApplicationError) as stopped:
        redo.redo([REDONE_PAGE])

    assert stopped.value.type == "BudgetSpent"
    assert stopped.value.non_retryable
    assert redo.sent_since() == []


def test_a_redone_email_replaces_the_campaigns_draft_and_its_variant(
    sqlite_engine: Engine,
) -> None:
    campaign = seed_campaign(
        sqlite_engine, CampaignSeed(status=db.DRAFTING, dag=EMAIL_DAG, draft=None)
    )
    worker = scripted_worker(sqlite_engine)
    run_step(worker, campaign, "email_writer", REPORT)
    redone = [
        {"subject": "Redone", "preheader": "P", "body": "B", "call_to_action": "Go"},
        {"subject": "Redone B", "preheader": "P", "body": "B", "call_to_action": "Go"},
    ]
    worker.agent.script([json.dumps(r) for r in redone])

    asyncio.run(
        worker.activities.redo_asset(RedoJob(str(campaign), REPORT, "email_writer", COMMENT, {}, 0))
    )

    with Session(sqlite_engine) as session:
        found = session.get_one(db.Campaign, campaign)
        assert (found.draft, found.variant_b) == (redone[0], redone[1])


EMAIL_DAG = {"steps": [{"id": "email_writer", "kind": "agent"}], "edges": []}
