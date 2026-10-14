"""A rejected asset in the campaign workflow, on Temporal's time-skipping server with stub
activities: only that asset is redone, the redone email is the one that sends, and a redo that
meets a spent budget waits for the owner to raise it. Approval waits again after each redo."""

from ace_engine.settings import RAISE_BUDGET_SIGNAL, REJECT_ASSET_SIGNAL
from campaign_worker.activities import RedoJob

from tests.support.dag import GOOD_DRAFT, edge, step
from tests.support.workflow_stubs import Cue, StubActivities, approve_every_approval, run_campaign

COMMENT = "Drop the hype"
FIRST = [GOOD_DRAFT, {**GOOD_DRAFT, "subject": "First B"}]
REDONE = [{**GOOD_DRAFT, "subject": "Redone"}, {**GOOD_DRAFT, "subject": "Redone B"}]
EMAIL_DAG = {
    "steps": [
        step("email_writer", "agent"),
        step("approve", "approval"),
        step("publish", "publish"),
    ],
    "edges": [edge("email_writer", "approve"), edge("approve", "publish")],
}
REJECT_THEN_APPROVE = [
    Cue("open_approval", 1, REJECT_ASSET_SIGNAL, ("email_writer", COMMENT)),
    *approve_every_approval()[1:],
]


def _stubs(redo_stops_at_budget: int = 0) -> StubActivities:
    return StubActivities(
        agent_outputs={"email_writer": FIRST},
        redo_outputs={"email_writer": REDONE},
        redo_stops_at_budget=redo_stops_at_budget,
    )


def test_only_the_rejected_asset_is_redone_and_approval_waits_again() -> None:
    stubs = run_campaign(EMAIL_DAG, _stubs(), cues=REJECT_THEN_APPROVE)

    [redo] = stubs.called("redo_asset")
    job = redo[0]
    assert isinstance(job, RedoJob)
    assert (job.step_id, job.comment) == ("email_writer", COMMENT)
    assert [c[2] for c in stubs.called("run_agent_step")] == ["email_writer"]
    assert len(stubs.called("open_approval")) == 2
    assert stubs.names()[-1] == "finish_run"


def test_a_redone_email_is_the_one_that_sends() -> None:
    stubs = run_campaign(EMAIL_DAG, _stubs(), cues=REJECT_THEN_APPROVE)

    [send] = stubs.called("send_email")
    assert send[1] == REDONE
    [publish] = stubs.called("publish_content")
    assert publish[1] == REDONE


def test_an_email_nobody_rejects_sends_as_the_writer_made_it() -> None:
    stubs = run_campaign(EMAIL_DAG, _stubs())

    assert stubs.called("redo_asset") == []
    [send] = stubs.called("send_email")
    assert send[1] == FIRST


def test_a_redo_that_meets_a_spent_budget_waits_for_the_owner_to_raise_it() -> None:
    cues = [
        *REJECT_THEN_APPROVE[:1],
        Cue("pause_for_budget", 1, RAISE_BUDGET_SIGNAL),
        *REJECT_THEN_APPROVE[1:],
    ]

    stubs = run_campaign(EMAIL_DAG, _stubs(redo_stops_at_budget=1), cues=cues)

    names = stubs.names()
    assert len(stubs.called("pause_for_budget")) == 1
    assert len(stubs.called("redo_asset")) == 2  # stopped once, then redone after the raise
    # Approval opens again only once the redo has gone through.
    second_opening = [i for i, n in enumerate(names) if n == "open_approval"][1]
    assert names.index("pause_for_budget") < names.index("resume_after_budget") < second_opening
    [send] = stubs.called("send_email")
    assert send[1] == REDONE
