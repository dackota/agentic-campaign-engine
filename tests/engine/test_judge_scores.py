"""The judge scores every asset of a run against the written rubric. The scores are stored
as run events and shown on the run and in the approval inbox; a score below the floor stops
the run with the reason, a score at or above it never does."""

import json
import random
from typing import Any

import pytest
from ace_engine import assets, db, judge
from ace_engine.agent_roles import ROLES, message_for
from ace_engine.dag import default_dag, ordered
from campaign_worker.activities import Activities
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.harness.scripted_agent import LOW_SCORE_MARKER, default_reply
from tests.support.dag import APPROVER, OWNER, REPORT
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import CampaignSeed, seed_campaign
from tests.support.settings import unit_settings

AS_OWNER = {"Authorization": f"Bearer {OWNER}"}
AS_APPROVER = {"Authorization": f"Bearer {APPROVER}"}
ASSETS = ["landing_page", "social"]
VERDICT: dict[str, Any] = {
    "scores": [
        {"step": "strategist", "score": 1, "reason": "Not an asset, not recorded"},
        {"step": "social", "score": 4, "reason": "Calm and clear"},
        {"step": "landing_page", "score": 5, "reason": "Accurate"},
    ]
}


def _record(engine: Engine, campaign: str, verdict: dict[str, Any]) -> list[str]:
    activities = Activities(unit_settings(), engine)
    return activities.record_scores(campaign, "judge", ASSETS, verdict)


def test_every_asset_gets_a_score_and_reason_in_events_and_on_the_run(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    campaign = seed_campaign(sqlite_engine)

    _record(sqlite_engine, str(campaign), VERDICT)

    scored = [e for e in db.events_after(sqlite_engine, campaign, 0) if e.status == db.SCORED]
    # The judge's order is kept, and a step that is not an asset is not scored.
    assert [(e.step, json.loads(e.reason or "")) for e in scored] == [
        ("social", {"score": 4, "reason": "Calm and clear"}),
        ("landing_page", {"score": 5, "reason": "Accurate"}),
    ]
    run = app_client.get(f"/campaigns/{campaign}", headers=AS_OWNER).json()
    assert {s["step"]: (s["score"], s["reason"]) for s in run["scores"]} == {
        "social": (4, "Calm and clear"),
        "landing_page": (5, "Accurate"),
    }


def test_the_approval_inbox_carries_each_assets_score_and_reason(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    campaign = seed_campaign(
        sqlite_engine,
        CampaignSeed(outputs={s: scripted_output(s) for s in ASSETS}),
    )
    _record(sqlite_engine, str(campaign), VERDICT)

    items = app_client.get("/inbox", headers=AS_APPROVER).json()

    assert {i["step"]: (i["score"], i["score_reason"]) for i in items} == {
        "social": (4, "Calm and clear"),
        "landing_page": (5, "Accurate"),
    }


def test_an_asset_not_yet_judged_has_no_score(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    seed_campaign(sqlite_engine, CampaignSeed(outputs={"social": scripted_output("social")}))

    [item] = app_client.get("/inbox", headers=AS_APPROVER).json()

    assert (item["score"], item["score_reason"]) == (None, None)


@pytest.mark.parametrize("score", range(judge.MIN_SCORE, judge.MAX_SCORE + 1))
def test_a_score_below_the_floor_blocks_with_the_reason_and_one_at_or_above_does_not(
    score: int,
) -> None:
    verdict = {"scores": [{"step": "landing_page", "score": score, "reason": "Too vague"}]}

    blocking = judge.blocking(verdict, ["landing_page"])

    expected = (
        [f"the judge scored landing_page {score} of 5, below the floor of 3: Too vague"]
        if score < 3
        else []
    )
    assert blocking == expected


def test_only_scores_of_the_runs_assets_can_block_it() -> None:
    rng = random.Random(11)
    steps = ["landing_page", "social", "one_pager", "strategist", "research", "judge"]
    for _ in range(200):
        scores: list[dict[str, Any]] = [
            {"step": s, "score": rng.randint(1, 5), "reason": "r"}
            for s in rng.sample(steps, rng.randint(0, len(steps)))
        ]
        verdict = {"scores": scores}

        blocked = judge.blocking(verdict, ASSETS)

        low = [s["step"] for s in scores if s["step"] in ASSETS and s["score"] < judge.FLOOR]
        assert [b.split()[3] for b in blocked] == low


@pytest.mark.parametrize(
    "verdict",
    [
        {"scores": [{"step": "x", "score": 6, "reason": "r"}]},
        {"scores": [{"step": "x", "score": 0, "reason": "r"}]},
        {"scores": [{"step": "x", "score": 3.5, "reason": "r"}]},
        {"scores": [{"step": "x", "score": 3, "reason": ""}]},
        {"scores": [{"step": "x", "score": "5", "reason": "r"}]},
        {"scores": [{"step": "x", "reason": "r"}]},
        {},
    ],
)
def test_a_verdict_that_breaks_the_contract_is_named(verdict: dict[str, object]) -> None:
    assert judge.score_problems(verdict) != []


def test_the_judge_is_sent_the_rubric_and_every_asset() -> None:
    context = {s: scripted_output(s) for s in ASSETS}

    message = message_for(ROLES["judge"], REPORT, context)

    assert judge.RUBRIC_PATH.read_text().splitlines()[0] in message
    assert "rubric" in message.lower()
    assert all(f"OUTPUT OF {s}" in message for s in ASSETS)


def test_the_scripted_judge_scores_each_asset_it_is_shown_and_never_the_prep_steps() -> None:
    context = {s: scripted_output(s) for s in ["strategist", "research", *ASSETS]}

    reply = default_reply(message_for(ROLES["judge"], REPORT, context))

    assert judge.score_problems(reply) == []
    assert [s["step"] for s in reply["scores"]] == ASSETS
    assert judge.blocking(reply, ASSETS) == []


def test_the_scripted_judge_scores_the_landing_page_below_the_floor_when_planted() -> None:
    context = {s: scripted_output(s) for s in ASSETS}

    reply = default_reply(message_for(ROLES["judge"], f"{REPORT}\n{LOW_SCORE_MARKER}", context))

    assert [b.split()[3] for b in judge.blocking(reply, ASSETS)] == ["landing_page"]


def test_a_campaign_with_no_workflow_is_judged_on_its_one_asset() -> None:
    dag = default_dag()

    assert assets.asset_steps(dag) == ["email_draft"]
    assert [s["id"] for s in ordered(dag)] == ["email_draft", "judge", "approval", "publish"]
    reply = default_reply(message_for(ROLES["judge"], REPORT, {"email_draft": {"subject": "s"}}))
    assert [s["step"] for s in reply["scores"]] == ["email_draft"]
