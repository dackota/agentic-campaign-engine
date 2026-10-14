"""The campaign workflow when a step fails: it retries by the policy in the DAG, a step that
keeps failing or runs too long stops the run with a reason that names the step, and the
retry-step signal runs the steps of that wave that are not done."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

from temporalio.exceptions import ApplicationError

from tests.support.campaign_run import StubActivities, running_campaign
from tests.support.dag import edge, step

A_DAY = timedelta(days=1)
FAST_RETRY = {"maximum_attempts": 2, "initial_interval_seconds": 0.1}
ONE_WRITER = {"steps": [step("writer", "agent", retry=FAST_RETRY)], "edges": []}


def _down(calls: list[str], failures: int) -> Callable[..., object]:
    """An agent step that fails with `agent unavailable` for its first `failures` calls."""

    def run_agent_step(_cid: str, _report: str, step_id: str, *_rest: object) -> object:
        calls.append(step_id)
        if len(calls) <= failures:
            raise ApplicationError("agent unavailable")
        return {"output": [{}, {}], "session": "s", "usage": {}}

    return run_agent_step


def test_step_retries_by_the_dag_policy_then_stops_with_a_named_reason() -> None:
    calls: list[str] = []
    stubs = StubActivities(run_agent_step=_down(calls, failures=99))

    async def scenario() -> None:
        async with running_campaign(ONE_WRITER, stubs) as run:
            await run.until("mark_failed")

    asyncio.run(scenario())

    # The DAG allows two attempts, where the default would allow three.
    assert calls == ["writer", "writer"]
    [(_, step_id, reason)] = stubs.args_of("mark_failed")
    assert step_id == "writer"
    assert reason == "step 'writer' failed after 2 attempts: agent unavailable"
    assert stubs.count("save_agent_output") == 0
    assert stubs.count("finish_run") == 0


def test_a_step_that_fails_once_is_retried_and_the_run_ends() -> None:
    calls: list[str] = []
    stubs = StubActivities(run_agent_step=_down(calls, failures=1))

    async def scenario() -> None:
        async with running_campaign(ONE_WRITER, stubs) as run:
            await run.finish()

    asyncio.run(scenario())

    assert calls == ["writer", "writer"]
    assert stubs.count("mark_failed") == 0
    assert stubs.count("save_agent_output") == 1
    assert stubs.count("finish_run") == 1


def test_step_times_out_by_the_dag_timeout() -> None:
    forever = asyncio.Event()

    async def hold(*_: object) -> object:
        await forever.wait()
        return None

    slow_writer = step("writer", "agent", timeout_seconds=1, retry={"maximum_attempts": 1})
    dag = {"steps": [slow_writer], "edges": []}
    stubs = StubActivities(run_agent_step=hold)

    async def scenario() -> None:
        async with running_campaign(dag, stubs) as run:
            await run.until("mark_failed")

    asyncio.run(scenario())

    [(_, step_id, reason)] = stubs.args_of("mark_failed")
    assert step_id == "writer"
    assert reason == "step 'writer' timed out after 1s (1 attempts)"


def test_retry_step_resumes_only_the_wave_that_failed_and_the_run_ends() -> None:
    dag = {
        "steps": [
            step("hold", "wait", duration_seconds=1),
            step("writer", "agent", retry=FAST_RETRY),
            step("preview", "render"),
        ],
        "edges": [edge("hold", "writer"), edge("writer", "preview")],
    }
    calls: list[str] = []
    stubs = StubActivities(run_agent_step=_down(calls, failures=2))

    async def scenario() -> None:
        async with running_campaign(dag, stubs) as run:
            await run.until("mark_failed")
            await run.sleep(A_DAY)
            # A failed run waits for the owner: nothing runs again by itself.
            assert calls == ["writer", "writer"]
            assert stubs.count("finish_run") == 0
            await run.retry_step()
            await run.finish()

    asyncio.run(scenario())

    # Two failed attempts, then the retry: the writer runs again, the wait step does not.
    assert calls == ["writer", "writer", "writer"]
    assert [a[2] for a in stubs.args_of("mark_step") if a[1] == "hold"] == ["started", "succeeded"]
    assert [a[2] for a in stubs.args_of("mark_step") if a[1] == "preview"] == [
        "started",
        "succeeded",
    ]
    assert stubs.count("mark_failed") == 1
    assert stubs.count("finish_run") == 1
