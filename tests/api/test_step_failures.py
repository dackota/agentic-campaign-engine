"""Seam 1 at fast depth: the retry-step action resumes a failed run to the end, and a
restarted worker picks up where the run left off, mid-writers and again while the run waits for
approval. How steps retry by the DAG policy, time out, and name their failure, and how each
step gets its own key, are proved lower: tests/engine/test_workflow_step_failures.py,
test_step_failure_reasons.py, test_step_keys.py and test_campaign_routes.py."""

import time
import uuid
from typing import Any

import httpx

from tests.api.helpers import (
    AWAITING,
    FAILED,
    FINISHED,
    REPORT,
    RETRYING,
    SENT,
    create_on,
    edge,
    events_until,
    marketo_sends,
    read_events,
    retry_step,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

FAST_RETRY = {"maximum_attempts": 2, "initial_interval_seconds": 0.1}
CALL_WAIT_SECONDS = 30
CALL_POLL_SECONDS = 0.05
PARALLEL_WRITERS = {
    "steps": [
        step("brief", "agent"),
        step("writer_a", "agent"),
        step("writer_b", "agent"),
        step("preview", "render"),
        step("approve", "approval"),
        step("publish", "publish"),
    ],
    "edges": [
        edge("brief", "writer_a"),
        edge("brief", "writer_b"),
        edge("writer_a", "preview"),
        edge("writer_b", "preview"),
        edge("preview", "approve"),
        edge("approve", "publish"),
    ],
}


def report(*markers: str) -> str:
    """A report no other test shares, so the scripted agent's failure count is this test's."""
    return "\n".join([*markers, REPORT, f"case {uuid.uuid4().hex}"])


def calls_for(stack: Stack, key: str) -> list[str]:
    """The agent message ids sent for the step with this idempotency key."""
    return [m for m in stack.agent.message_ids() if m.startswith(f"{key}:")]


def key_of(campaign: dict[str, Any], step_id: str) -> str:
    [found] = [s for s in campaign["steps"] if s["id"] == step_id]
    key: str = found["idempotency_key"]
    return key


def statuses(events: list[dict[str, Any]], step_id: str) -> list[str]:
    return [e["status"] for e in events if e["step"] == step_id]


def wait_for_call(stack: Stack, key: str) -> None:
    deadline = time.monotonic() + CALL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if calls_for(stack, key):
            return
        time.sleep(CALL_POLL_SECONDS)
    raise AssertionError(f"the agent never got a call for {key}: {stack.agent.message_ids()}")


def test_retry_step_resumes_the_run_to_the_end(stack: Stack, api: httpx.Client) -> None:
    name = workflow_name()
    dag = {
        "steps": [
            step("prepare", "render"),
            step("writer", "agent", retry=FAST_RETRY),
            step("preview", "render"),
        ],
        "edges": [edge("prepare", "writer"), edge("writer", "preview")],
    }
    save_workflow(api, name, dag)
    created = create_on(api, name, report("[agent:down-2]"))
    campaign_id = created["id"]
    failed = until_status(api, campaign_id, FAILED, FINISHED)
    assert failed["status"] == FAILED
    stopped_at = read_events(api, campaign_id)[-1]["seq"]

    response = retry_step(api, campaign_id)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == RETRYING
    assert response.json()["failure_reason"] is None
    done = until_status(api, campaign_id, FINISHED, FAILED)
    events = events_until(api, campaign_id, done["status"])

    assert done["status"] == FINISHED and done["draft"]["subject"]
    assert statuses(events, "prepare") == ["started", "succeeded"]
    assert statuses(events, "writer")[-1] == "succeeded"
    assert statuses(events, "preview") == ["started", "succeeded"]
    assert [e["seq"] for e in events if e["step"] == "preview"][0] > stopped_at
    assert (events[-1]["step"], events[-1]["status"]) == ("run", FINISHED)
    resumed = read_events(api, campaign_id, after=stopped_at)
    assert (resumed[0]["step"], resumed[0]["status"]) == ("run", RETRYING)
    assert resumed[-1]["status"] == FINISHED
    # Two failed attempts, then one call per A/B variant.
    assert len(calls_for(stack, key_of(created, "writer"))) == 4


def test_worker_restart_during_parallel_writers_resumes_from_last_finished_step(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    name = workflow_name()
    save_workflow(api, name, PARALLEL_WRITERS)
    # The slow agent holds each reply, so the writers are mid-call when the worker stops.
    created = create_on(api, name, report("[agent:slow]"))
    campaign_id = created["id"]
    wait_for_call(stack, key_of(created, "writer_a"))

    stack.restart_worker()

    assert until_status(api, campaign_id, AWAITING)["status"] == AWAITING
    # A second restart, while the run waits for a human: the wait is not lost.
    stack.restart_worker()
    assert api.get(f"/campaigns/{campaign_id}").json()["status"] == AWAITING
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)
    events = events_until(api, campaign_id, SENT)

    assert sent["receipt"]
    assert statuses(events, "brief") == ["started", "succeeded"]
    assert len(calls_for(stack, key_of(created, "brief"))) == 2
    for writer in ("writer_a", "writer_b"):
        assert statuses(events, writer)[-1] == "succeeded"
    assert len(marketo_sends(stack, campaign_id)) == 1
