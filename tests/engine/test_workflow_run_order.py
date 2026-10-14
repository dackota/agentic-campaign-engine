"""The engine follows the run's DAG: parallel writers start together, a step waits for every
parent, approval holds the publish step back, and a workflow with no approval or publish
step finishes. Runs the real workflow on stub activities."""

import asyncio
from typing import Any

from ace_engine.settings import APPROVE_SIGNAL
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from tests.support.dag import edge, step
from tests.support.run_stubs import (
    FINISHED,
    StubActivities,
    run_workflow,
    time_skipping_env,
    until,
)

PARALLEL_WRITERS_DAG = {
    "steps": [
        step("brief", "agent"),
        step("writer_a", "agent"),
        step("writer_b", "agent"),
        step("preview", "render"),
        step("approve", "approval"),
        step("cool_off", "wait", duration_seconds=1),
        step("publish", "publish"),
    ],
    "edges": [
        edge("brief", "writer_a"),
        edge("brief", "writer_b"),
        edge("writer_a", "preview"),
        edge("writer_b", "preview"),
        edge("preview", "approve"),
        edge("approve", "cool_off"),
        edge("cool_off", "publish"),
    ],
}
# Real time the open approval is left alone, for any step past it to show.
HELD_SECONDS = 0.3


def _index_of(stubs: StubActivities, name: str, step_id: str, *rest: object) -> int:
    return stubs.calls.index((name, (step_id, *rest)))


def _succeeded_at(stubs: StubActivities, dag_step: dict[str, Any]) -> int:
    """Where in the run order the step succeeded: an agent step saves its output, a publish
    step is marked sent, the rest are marked succeeded."""
    step_id = dag_step["id"]
    if dag_step["kind"] == "agent":
        return _index_of(stubs, "save_agent_output", step_id)
    if dag_step["kind"] == "publish":
        return next(
            i for i, (n, a) in enumerate(stubs.calls) if n == "mark_sent" and a[0] == step_id
        )
    return _index_of(stubs, "mark_step", step_id, "succeeded")


def test_engine_runs_parallel_writers_waits_for_approval_then_publishes_in_dag_order() -> None:
    stubs = StubActivities()
    held: list[tuple[str, tuple[object, ...]]] = []

    async def hold_then_approve(
        env: WorkflowEnvironment, handle: WorkflowHandle[Any, Any], stubs: StubActivities
    ) -> None:
        await until(lambda: bool(stubs.called("announce_approval")))
        await asyncio.sleep(HELD_SECONDS)
        held.extend(stubs.calls)
        await handle.signal(APPROVE_SIGNAL)

    async def go() -> str:
        async with time_skipping_env() as env:
            return await run_workflow(env, PARALLEL_WRITERS_DAG, stubs, hold_then_approve)

    outcome = asyncio.run(go())

    steps = {s["id"]: s for s in PARALLEL_WRITERS_DAG["steps"]}
    assert outcome == FINISHED
    # While the approval is open nothing past it has run: not the approval's own success, not
    # the cool-off, not the send.
    after_approval = {"approve", "cool_off", "publish"}
    assert [c for c in held if c[0] == "mark_step" and c[1][0] in after_approval] == []
    assert [c for c in held if c[0] in {"send_email", "publish_content", "mark_sent"}] == []
    for e in PARALLEL_WRITERS_DAG["edges"]:
        assert _succeeded_at(stubs, steps[e["from"]]) < _succeeded_at(stubs, steps[e["to"]])
    for writer in ("writer_a", "writer_b"):
        assert _index_of(stubs, "run_agent_step", writer) < _succeeded_at(stubs, steps["preview"])
    assert len(stubs.called("send_email")) == 1
    assert stubs.calls[-1] == ("finish_run", ())


def test_workflow_without_approval_or_publish_finishes_without_sending() -> None:
    dag = {
        "steps": [step("draft", "agent"), step("pdf", "render")],
        "edges": [edge("draft", "pdf")],
    }
    stubs = StubActivities()

    async def go() -> str:
        async with time_skipping_env() as env:
            return await run_workflow(env, dag, stubs)

    outcome = asyncio.run(go())

    assert outcome == FINISHED
    assert stubs.called("finish_run") == [()]
    assert stubs.called("send_email") == []
    assert stubs.called("mark_failed") == []


def test_a_step_waits_for_a_team_slot_and_gives_it_back_when_done() -> None:
    dag = {"steps": [step("draft", "agent")], "edges": []}
    stubs = StubActivities(slot_refusals=2)

    async def go() -> str:
        async with time_skipping_env() as env:
            return await run_workflow(env, dag, stubs)

    outcome = asyncio.run(go())

    names = [
        name for name, _ in stubs.calls if name.endswith("_step_slot") or name == "run_agent_step"
    ]
    assert outcome == FINISHED
    assert names == ["claim_step_slot"] * 3 + ["run_agent_step", "release_step_slot"]
