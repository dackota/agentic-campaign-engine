"""Property tests: any workflow the validator accepts is a sound graph, and any workflow the
engine runs either ends or stops with a named reason, never hangs and never publishes a step
twice.

Workflows come from a seeded generator (random kinds, edges, retry policies, timeouts) plus
adversarial fixed cases; the stub agent fails on cue or breaks its contract for some."""

import asyncio
import contextlib
import random
import time
from collections import Counter
from typing import Any

from ace_engine import dag as graph
from ace_engine.settings import APPROVE_SIGNAL
from ace_engine.workflow_spec import MAX_SHAPE_ERRORS, validate
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment

from tests.support.dag import edge, step
from tests.support.run_stubs import (
    FAILED,
    FINISHED,
    POLL_SECONDS,
    AgentBehavior,
    StubActivities,
    run_workflow,
    time_skipping_env,
)

SEED = 32
GENERATED_CASES = 14
MIN_ACCEPTED = 8
MAX_STEPS = 6
RETRY_INTERVAL_SECONDS = 0.01
QUIET_SECONDS = 0.2
EDGE_CHANCE = 0.35
KINDS = ["agent", "render", "approval", "publish", "wait"]
# The ways the stub agent misbehaves, by the cue a case carries.
NO_FAILURES = 0
FAIL_FIRST_ATTEMPTS = {"": NO_FAILURES, "down-1": 1, "down-2": 2, "down-9": 9}
BAD_JSON = "bad-json"
CUES = [*FAIL_FIRST_ATTEMPTS, BAD_JSON]
# Structure-only generator: ids from a small pool so ids repeat, edges that loop or dangle.
HOSTILE_CASES = 600
HOSTILE_IDS = ["a", "b", "c", "d", "ghost"]
MIN_HOSTILE_ACCEPTED = 10


def _random_step(rng: random.Random, index: int) -> dict[str, Any]:
    kind = rng.choice(KINDS)
    extra: dict[str, Any] = {}
    if kind == "wait":
        extra["duration_seconds"] = 1
    if kind in ("agent", "publish"):
        extra["retry"] = {
            "maximum_attempts": rng.randint(1, 3),
            "initial_interval_seconds": RETRY_INTERVAL_SECONDS,
        }
        if rng.random() < 0.5:
            extra["timeout_seconds"] = rng.choice([5, 30, 60])
    return step(f"s{index}_{kind}", kind, **extra)


def _random_dag(rng: random.Random) -> dict[str, Any]:
    steps = [_random_step(rng, i) for i in range(rng.randint(1, MAX_STEPS))]
    edges = [
        edge(a["id"], b["id"])
        for i, a in enumerate(steps)
        for b in steps[i + 1 :]
        if rng.random() < EDGE_CHANCE
    ]
    return {"steps": steps, "edges": edges}


def _hostile_dag(rng: random.Random) -> dict[str, Any]:
    steps = [
        step(rng.choice(HOSTILE_IDS[:-1]), rng.choice(KINDS)) for _ in range(rng.randint(1, 5))
    ]
    edges = [
        edge(rng.choice(HOSTILE_IDS), rng.choice(HOSTILE_IDS)) for _ in range(rng.randint(0, 6))
    ]
    return {"steps": steps, "edges": edges}


def _fixed_dags() -> list[dict[str, Any]]:
    one_retry = {"maximum_attempts": 1, "initial_interval_seconds": RETRY_INTERVAL_SECONDS}
    return [
        # Publish needs an agent and an approval on every path: two writers, one approval.
        {
            "steps": [
                step("a", "agent", retry=one_retry),
                step("b", "agent", retry=one_retry),
                step("ok", "approval"),
                step("pub", "publish", retry=one_retry),
            ],
            "edges": [edge("a", "ok"), edge("b", "ok"), edge("ok", "pub")],
        },
        # Two publish steps after one approval.
        {
            "steps": [
                step("a", "agent", retry=one_retry),
                step("ok", "approval"),
                step("p1", "publish", retry=one_retry),
                step("p2", "publish", retry=one_retry),
            ],
            "edges": [edge("a", "ok"), edge("ok", "p1"), edge("ok", "p2")],
        },
        # Two approvals in a row, then a publish.
        {
            "steps": [
                step("a", "agent", retry=one_retry),
                step("ok1", "approval"),
                step("ok2", "approval"),
                step("pub", "publish"),
            ],
            "edges": [edge("a", "ok1"), edge("ok1", "ok2"), edge("ok2", "pub")],
        },
    ]


def _accepted_cases() -> list[tuple[dict[str, Any], str]]:
    rng = random.Random(SEED)
    dags = _fixed_dags() + [_random_dag(rng) for _ in range(GENERATED_CASES)]
    accepted = [dag for dag in dags if validate(dag) == []]
    return [(dag, CUES[i % len(CUES)]) for i, dag in enumerate(accepted)]


def _is_sound(dag: dict[str, Any]) -> None:
    """What an accepted workflow guarantees the engine."""
    order = [s["id"] for s in graph.ordered(dag)]
    kinds = {s["id"]: s["kind"] for s in dag["steps"]}
    assert not graph.has_cycle(dag), dag
    assert len(order) == len(dag["steps"]) == len(set(order)), dag
    for e in dag["edges"]:
        assert order.index(e["from"]) < order.index(e["to"]), dag
    for step_id, kind in kinds.items():
        if kind == graph.PUBLISH:
            before = {kinds[a] for a in graph.ancestors(dag, step_id)}
            assert {graph.APPROVAL, graph.AGENT} <= before, (step_id, dag)


def test_an_accepted_workflow_is_acyclic_ordered_and_publishes_only_after_approval() -> None:
    rng = random.Random(SEED)
    accepted = 0
    for dag in (_random_dag(rng) for _ in range(HOSTILE_CASES)):
        if validate(dag) == []:
            accepted += 1
            _is_sound(dag)

    assert accepted >= MIN_HOSTILE_ACCEPTED


def test_the_validator_never_raises_and_accepted_hostile_workflows_are_sound() -> None:
    rng = random.Random(SEED)
    accepted = 0
    for _ in range(HOSTILE_CASES):
        dag = _hostile_dag(rng)
        rejections = validate(dag)
        assert len(rejections) <= MAX_SHAPE_ERRORS, dag
        assert all(r.rule and r.message for r in rejections), dag
        if rejections == []:
            accepted += 1
            _is_sound(dag)

    assert accepted >= MIN_HOSTILE_ACCEPTED


def _agent_for(cue: str) -> AgentBehavior:
    attempts: Counter[str] = Counter()

    async def agent(step_id: str) -> dict[str, Any]:
        attempts[step_id] += 1
        if cue == BAD_JSON:
            raise ApplicationError("agent reply broke its contract", non_retryable=True)
        if attempts[step_id] <= FAIL_FIRST_ATTEMPTS[cue]:
            raise ApplicationError("agent unavailable")
        return {"output": {"step": step_id}, "session": step_id, "usage": {}}

    return agent


async def _approve_whenever_asked(
    env: WorkflowEnvironment, handle: WorkflowHandle[Any, Any], stubs: StubActivities
) -> None:
    """Stand in for the approver: one approval for every one the run opens, once the run has
    been quiet for a moment. An approval that lands in the same instant as a failing sibling
    step stalls the test server's workflow task, so the approver waits for the failure."""
    answered, seen, quiet_since = 0, 0, time.monotonic()
    while not stubs.failed.is_set():
        if (await handle.describe()).status != WorkflowExecutionStatus.RUNNING:
            return
        if len(stubs.calls) != seen:
            seen, quiet_since = len(stubs.calls), time.monotonic()
        asked = len(stubs.called("open_approval"))
        if asked > answered and time.monotonic() - quiet_since >= QUIET_SECONDS:
            with contextlib.suppress(RPCError):  # the run ended since the check above
                await handle.signal(APPROVE_SIGNAL)
            answered += 1
        await asyncio.sleep(POLL_SECONDS)


def test_accepted_workflows_end_or_stop_with_a_reason_and_publish_each_step_at_most_once() -> None:
    cases = _accepted_cases()
    assert len(cases) >= MIN_ACCEPTED, f"only {len(cases)} generated workflows were accepted"

    async def run_all() -> list[tuple[dict[str, Any], str, str, StubActivities]]:
        results = []
        async with time_skipping_env() as env:
            for dag, cue in cases:
                stubs = StubActivities(_agent_for(cue))
                outcome = await run_workflow(env, dag, stubs, _approve_whenever_asked)
                results.append((dag, cue, outcome, stubs))
        return results

    for dag, cue, outcome, stubs in asyncio.run(run_all()):
        publishes = [s["id"] for s in dag["steps"] if s["kind"] == graph.PUBLISH]
        sends = Counter(args[0] for args in stubs.called("send_email"))
        marks = Counter(args[0] for args in stubs.called("mark_sent"))
        assert outcome in (FINISHED, FAILED), (dag, cue)
        assert all(sends[p] <= 1 and marks[p] <= 1 for p in publishes), (dag, cue)
        if outcome == FINISHED:
            assert stubs.called("mark_failed") == [], (dag, cue)
            assert stubs.called("finish_run") == [()], (dag, cue)
            assert all(sends[p] == 1 and marks[p] == 1 for p in publishes), (dag, cue)
        else:
            [(failed_step, reason)] = stubs.called("mark_failed")
            assert stubs.called("finish_run") == [], (dag, cue)
            assert failed_step in {s["id"] for s in dag["steps"]}, (dag, cue)
            assert reason and repr(failed_step) in str(reason), (dag, cue, reason)
