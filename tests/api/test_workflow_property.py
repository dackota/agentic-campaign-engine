"""Property test at seam 1, fast depth: any workflow the Campaign API accepts either runs to
the end or stops with a named reason. It never hangs and never publishes twice.

Workflows come from a seeded generator (random kinds, edges, retry policies, timeouts) plus
adversarial fixed cases; the scripted agent fails on cue or breaks its contract for some."""

import random
import time
import uuid
from typing import Any

import httpx

from tests.api.helpers import (
    AWAITING,
    FAILED,
    FINISHED,
    REPORT,
    SENT,
    edge,
    events_until,
    marketo_sends,
    step,
    workflow_name,
)
from tests.harness.stack import Stack

SEED = 32
GENERATED_CASES = 14
MIN_ACCEPTED = 8
MAX_STEPS = 6
EDGE_CHANCE = 0.35
RUN_DEADLINE_SECONDS = 60
POLL_SECONDS = 0.2
KINDS = ["agent", "render", "approval", "publish", "wait"]
ENDS = {SENT, FINISHED}
AGENT_CUES = ["", "[agent:down-1]", "[agent:down-2]", "[agent:down-9]", "[agent:bad-json]"]


def _random_step(rng: random.Random, index: int) -> dict[str, Any]:
    kind = rng.choice(KINDS)
    extra: dict[str, Any] = {}
    if kind == "wait":
        extra["duration_seconds"] = 1
    if kind in ("agent", "publish"):
        extra["retry"] = {
            "maximum_attempts": rng.randint(1, 3),
            "initial_interval_seconds": 0.1,
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


def _fixed_dags() -> list[dict[str, Any]]:
    one_retry = {"maximum_attempts": 1, "initial_interval_seconds": 0.1}
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
        # Two publish steps after one approval must still send once.
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


def _cases() -> list[tuple[dict[str, Any], str]]:
    rng = random.Random(SEED)
    dags = _fixed_dags() + [_random_dag(rng) for _ in range(GENERATED_CASES)]
    return [(dag, rng.choice(AGENT_CUES)) for dag in dags]


def _run_to_rest(api: httpx.Client, approver: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Approve whenever the run waits for a human; return it once it ends or stops."""
    deadline = time.monotonic() + RUN_DEADLINE_SECONDS
    campaign: dict[str, Any] = {}
    while time.monotonic() < deadline:
        campaign = api.get(f"/campaigns/{campaign_id}").json()
        if campaign["status"] in ENDS | {FAILED}:
            return campaign
        if campaign["status"] == AWAITING:
            approver.post(f"/campaigns/{campaign_id}/approve")
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"run hung: {campaign}")


def test_any_accepted_workflow_ends_or_stops_with_a_reason_and_publishes_at_most_once(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    accepted = 0
    for dag, cue in _cases():
        name = workflow_name("prop")
        saved = api.post(f"/workflows/{name}/versions", json=dag)
        assert saved.status_code in (201, 422), (dag, saved.text)
        if saved.status_code == 422:
            continue
        accepted += 1
        report = f"{cue}\n{REPORT}\ncase {uuid.uuid4().hex}"
        created = api.post("/campaigns", json={"report": report, "workflow": name})
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]

        rest = _run_to_rest(api, approver, campaign_id)
        last = events_until(api, campaign_id, rest["status"])[-1]
        sends = marketo_sends(stack, campaign_id)

        assert (last["step"], last["status"]) == ("run", rest["status"]), (dag, cue)
        if rest["status"] == FAILED:
            assert rest["failure_reason"] and last["reason"] == rest["failure_reason"], dag
        assert len(sends) <= 1, (dag, cue, sends)
        if rest["status"] == SENT:
            assert len(sends) == 1, (dag, cue, rest)
    assert accepted >= MIN_ACCEPTED, f"only {accepted} generated workflows were accepted"
