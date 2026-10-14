"""The campaign workflow at a campaign's budget: a model step that finds the budget spent
pauses the run before its model call, and only a raise of the budget lets it try again."""

import asyncio
from datetime import timedelta

from ace_engine.cost import BUDGET_SPENT
from temporalio.exceptions import ApplicationError

from tests.support.campaign_run import StubActivities, running_campaign
from tests.support.dag import edge, step

TWO_WRITERS = {
    "steps": [step("first", "agent"), step("second", "agent")],
    "edges": [edge("first", "second")],
}
A_DAY = timedelta(days=1)


def _budget_spent_until_raised(attempts: list[str]) -> StubActivities:
    """Agent steps that find the budget spent for the second step, until it is raised."""
    is_raised = False

    def run_agent_step(_cid: str, _report: str, step_id: str, *_rest: object) -> object:
        attempts.append(step_id)
        if step_id == "second" and not is_raised:
            raise ApplicationError("the budget is spent", type=BUDGET_SPENT, non_retryable=True)
        return {"output": {"step": step_id}, "session": f"s-{step_id}", "usage": {}}

    def resume_after_budget(_cid: str) -> None:
        nonlocal is_raised
        is_raised = True

    return StubActivities(run_agent_step=run_agent_step, resume_after_budget=resume_after_budget)


def test_run_pauses_before_the_next_model_step_at_its_budget() -> None:
    attempts: list[str] = []
    stubs = _budget_spent_until_raised(attempts)

    async def scenario() -> None:
        async with running_campaign(TWO_WRITERS, stubs) as run:
            await run.until("pause_for_budget")
            await run.sleep(A_DAY)

    asyncio.run(scenario())

    # The first step finished and was saved; the second stopped at the budget, once, and
    # the run is held there: not resumed, not finished, not failed.
    assert [args[1] for args in stubs.args_of("save_agent_output")] == ["first"]
    assert attempts == ["first", "second"]
    assert stubs.count("pause_for_budget") == 1
    assert stubs.count("resume_after_budget") == 0
    assert stubs.count("finish_run") == 0
    assert stubs.count("mark_failed") == 0
    # The team slot the paused step held was given back.
    assert stubs.count("claim_step_slot") == stubs.count("release_step_slot")


def test_raising_the_budget_resumes_the_paused_step_and_the_run_ends() -> None:
    attempts: list[str] = []
    stubs = _budget_spent_until_raised(attempts)

    async def scenario() -> None:
        async with running_campaign(TWO_WRITERS, stubs) as run:
            await run.until("pause_for_budget")
            await run.raise_budget()
            await run.finish()

    asyncio.run(scenario())

    assert attempts == ["first", "second", "second"]
    assert stubs.count("resume_after_budget") == 1
    assert [args[1] for args in stubs.args_of("save_agent_output")] == ["first", "second"]
    assert stubs.count("finish_run") == 1
    assert stubs.count("mark_failed") == 0


def test_one_raise_wakes_every_writer_waiting_at_the_budget() -> None:
    two_waiting = {"steps": [step("a", "agent"), step("b", "agent")], "edges": []}
    attempts: list[str] = []
    is_raised = False

    def run_agent_step(_cid: str, _report: str, step_id: str, *_rest: object) -> object:
        attempts.append(step_id)
        if not is_raised:
            raise ApplicationError("the budget is spent", type=BUDGET_SPENT, non_retryable=True)
        return {"output": {}, "session": f"s-{step_id}", "usage": {}}

    def resume_after_budget(_cid: str) -> None:
        nonlocal is_raised
        is_raised = True

    stubs = StubActivities(run_agent_step=run_agent_step, resume_after_budget=resume_after_budget)

    async def scenario() -> None:
        async with running_campaign(two_waiting, stubs) as run:
            await run.until("pause_for_budget", times=2)
            await run.raise_budget()
            await run.finish()

    asyncio.run(scenario())

    assert sorted(attempts) == ["a", "a", "b", "b"]
    assert sorted(str(args[1]) for args in stubs.args_of("save_agent_output")) == ["a", "b"]
    assert stubs.count("finish_run") == 1
