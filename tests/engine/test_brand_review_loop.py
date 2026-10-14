"""A writer step with review rounds sends its draft to the brand reviewer, takes fixes back
in the same writer Session, and after two rounds flags what is still wrong for a human. The
worker's agent step runs against the scripted agent in-process."""

import json
from typing import Any

import pytest
from ace_engine import brand_review, db
from ace_engine.contracts import REPORT_MARKER
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.dag import REPORT
from tests.support.scripted_worker import ScriptedWorker, run_step, scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

WRITER = "landing_page"
PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
FIXED = {**PAGE, "body": "Better"}
PASS = {"verdict": "pass", "issues": []}
FIX = {
    "verdict": "fix",
    "issues": [{"check": "banned_claim", "detail": "100% protection is a banned claim"}],
}


class ReviewedStep:
    """One writer step run with `review_rounds`, the agent answering with `replies`."""

    def __init__(
        self, engine: Engine, replies: list[dict[str, Any]], review_rounds: int = 2
    ) -> None:
        self.engine = engine
        self.campaign = seed_campaign(engine, CampaignSeed(status=db.DRAFTING))
        self.worker: ScriptedWorker = scripted_worker(engine)
        self.worker.agent.script([json.dumps(r) for r in replies])
        self.result = run_step(self.worker, self.campaign, WRITER, REPORT, review_rounds)

    def events(self, status: str) -> list[db.RunEvent]:
        return [e for e in db.events_after(self.engine, self.campaign, 0) if e.status == status]

    def flags(self) -> list[db.RunEvent]:
        with Session(self.engine) as session:
            return db.review_flags(session, self.campaign)

    def writer_message_ids(self) -> list[str]:
        return [i for i in self.worker.agent.message_ids() if ":review" not in i]


def test_a_passing_draft_shows_no_flags(sqlite_engine: Engine) -> None:
    step = ReviewedStep(sqlite_engine, [PAGE, PASS])

    assert step.result["output"] == PAGE
    assert step.events(db.REVIEW_FIX) == []
    assert step.events(db.FLAGGED) == []
    assert step.flags() == []


def test_a_fix_then_a_pass_sends_one_fix_to_the_same_writer_session(sqlite_engine: Engine) -> None:
    step = ReviewedStep(sqlite_engine, [PAGE, FIX, FIXED, PASS])

    [fix] = step.events(db.REVIEW_FIX)
    assert (fix.step, fix.session) == (WRITER, step.result["session"])
    assert "banned claim" in (fix.reason or "")
    assert step.result["output"]["body"] == "Better"
    assert step.flags() == []
    ids = step.writer_message_ids()
    assert len(ids) == 2 and len(set(ids)) == 2
    assert all(i.startswith(step.result["session"]) for i in ids)
    # The fix goes to the session the agent issued for the first draft, not a new one.
    first, fix_message = [m for m in step.worker.messages_sent() if ":review" not in m[0]]
    assert first[1] is None
    assert fix_message[1] == step.result["writer_sessions"][0]


def test_a_draft_that_never_passes_stops_after_two_rounds_and_is_flagged(
    sqlite_engine: Engine,
) -> None:
    step = ReviewedStep(sqlite_engine, [PAGE, FIX, PAGE, FIX, PAGE, FIX])

    [flagged] = step.events(db.FLAGGED)
    assert len(step.events(db.REVIEW_FIX)) == 2
    assert flagged.step == WRITER
    assert "banned claim" in (flagged.reason or "")
    [flag] = step.flags()
    assert json.loads(flag.reason or "[]")[0]["check"] == "banned_claim"


@pytest.mark.parametrize("review_rounds", [2, 3, 5, 100])
def test_no_number_of_review_rounds_asks_for_more_than_the_fix_round_limit(
    sqlite_engine: Engine, review_rounds: int
) -> None:
    always_fix: list[dict[str, Any]] = [PAGE, FIX] * (brand_review.MAX_FIX_ROUNDS + 1)

    step = ReviewedStep(sqlite_engine, always_fix, review_rounds)

    assert len(step.events(db.REVIEW_FIX)) == brand_review.MAX_FIX_ROUNDS
    assert len(step.events(db.FLAGGED)) == 1
    assert len(step.worker.agent.message_ids()) == len(always_fix)


# The reviewer's verdict contract and the messages it and the writer are sent are pure text.
@pytest.mark.parametrize(
    "verdict",
    [PASS, FIX, {"verdict": "fix", "issues": [{"check": "length", "detail": "long"}]}],
)
def test_a_verdict_that_meets_the_contract_has_no_problems(verdict: dict[str, Any]) -> None:
    assert brand_review.verdict_problems(verdict) == []


@pytest.mark.parametrize(
    "verdict",
    [
        {},
        {"verdict": "maybe", "issues": []},
        {"verdict": "fix", "issues": []},
        {"verdict": "pass"},
        {"verdict": "fix", "issues": [{"check": "vibes", "detail": "x"}]},
        {"verdict": "fix", "issues": [{"check": "length"}]},
        "pass",
    ],
)
def test_a_verdict_that_breaks_the_contract_is_named(verdict: object) -> None:
    assert brand_review.verdict_problems(verdict) != []


def test_the_reviewer_is_sent_the_draft_what_came_before_and_the_report_last() -> None:
    message = brand_review.review_message(PAGE, {"strategist": {"angle": "calm"}}, REPORT)

    assert message.startswith(brand_review.BRAND_REVIEWER.prompt)
    assert f"DRAFT: {json.dumps(PAGE)}" in message
    assert "OUTPUT OF strategist: {'angle': 'calm'}" in message
    assert message.endswith(f"{REPORT_MARKER}\n{REPORT}")


def test_the_writer_is_sent_each_issue_to_fix_after_its_own_prompt() -> None:
    issues = [{"check": "length", "detail": "too long"}, {"check": "banned_claim", "detail": "x"}]

    message = brand_review.fix_message("WRITER PROMPT", issues)

    assert message.startswith("WRITER PROMPT\n\n")
    assert message.endswith("- length: too long\n- banned_claim: x")
    assert brand_review.REVISION_OPENING in message
