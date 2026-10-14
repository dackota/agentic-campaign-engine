"""The judge step in the campaign workflow, on Temporal's time-skipping server with stub
activities: the judge is shown the assets, its scores are recorded for the assets, and a score
below the floor ends the run failed with the judge's reason instead of reaching approval."""

from typing import Any

from tests.support.dag import edge, step
from tests.support.workflow_stubs import StubActivities, run_campaign

BELOW_FLOOR = "the judge scored landing_page 2 of 5, below the floor of 3: Too vague"
VERDICT = {"scores": [{"step": "landing_page", "score": 4, "reason": "Clear"}]}
JUDGED = {
    "steps": [
        step("strategist", "agent"),
        step("landing_page", "agent"),
        step("social", "agent"),
        step("judge", "agent"),
        step("approve", "approval"),
    ],
    "edges": [
        edge("strategist", "landing_page"),
        edge("strategist", "social"),
        edge("landing_page", "judge"),
        edge("social", "judge"),
        edge("judge", "approve"),
    ],
}


def _stubs(reasons: list[str]) -> StubActivities:
    return StubActivities(agent_outputs={"judge": VERDICT}, score_reasons=reasons)


def test_the_judge_is_shown_every_asset_and_its_scores_are_recorded_for_the_assets() -> None:
    stubs = run_campaign(JUDGED, _stubs([]))

    [judge_call] = [c for c in stubs.called("run_agent_step") if c[2] == "judge"]
    context: dict[str, Any] = judge_call[3]  # type: ignore[assignment]
    assert {"landing_page", "social"} <= set(context)
    [recorded] = stubs.called("record_scores")
    assert recorded[1:] == ("judge", ["landing_page", "social"], VERDICT)


def test_a_score_below_the_floor_fails_the_run_with_the_reason_before_approval() -> None:
    stubs = run_campaign(JUDGED, _stubs([BELOW_FLOOR]))

    assert [c[1:] for c in stubs.called("mark_failed")] == [("judge", BELOW_FLOOR)]
    assert stubs.called("open_approval") == []
    assert stubs.called("finish_run") == []


def test_scores_that_clear_the_floor_let_the_run_reach_approval_and_finish() -> None:
    stubs = run_campaign(JUDGED, _stubs([]))

    assert stubs.called("mark_failed") == []
    assert len(stubs.called("open_approval")) == 1
    assert len(stubs.called("finish_run")) == 1
