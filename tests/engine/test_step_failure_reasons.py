"""How a step's policy is read from the DAG, and the reason a failed step gives: it names the
step, the attempts, and what the agent itself said."""

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from ace_engine import invoker
from campaign_worker.workflow import StepFailed, StepPolicy, _as_step_failure, _failed, step_policy
from temporalio.exceptions import ActivityError, ApplicationError, RetryState, TimeoutType
from temporalio.exceptions import TimeoutError as ActivityTimedOut

from tests.engine.agent_replies import task_reply

AGENT_DEFAULT = StepPolicy(timedelta(minutes=5), 3, timedelta(seconds=1))
PUBLISH_DEFAULT = StepPolicy(timedelta(minutes=1), 5, timedelta(seconds=1))
TWO_ATTEMPTS = StepPolicy(timedelta(seconds=30), 2, timedelta(seconds=0.1))


def _activity_error(cause: BaseException, retry_state: RetryState | None) -> ActivityError:
    error = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="run_agent_step",
        activity_id="1",
        retry_state=retry_state,
    )
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ({"id": "a", "kind": "agent"}, AGENT_DEFAULT),
        ({"id": "p", "kind": "publish"}, PUBLISH_DEFAULT),
        (
            {"id": "a", "kind": "agent", "retry": {"maximum_attempts": 2}},
            StepPolicy(timedelta(minutes=5), 2, timedelta(seconds=1)),
        ),
        (
            {"id": "a", "kind": "agent", "max_attempts": 4},
            StepPolicy(timedelta(minutes=5), 4, timedelta(seconds=1)),
        ),
        # The retry block wins over the builder's shorthand.
        (
            {"id": "a", "kind": "agent", "max_attempts": 4, "retry": {"maximum_attempts": 2}},
            StepPolicy(timedelta(minutes=5), 2, timedelta(seconds=1)),
        ),
        (
            {"id": "a", "kind": "agent", "retry": {"initial_interval_seconds": 0.1}},
            StepPolicy(timedelta(minutes=5), 3, timedelta(seconds=0.1)),
        ),
        (
            {"id": "p", "kind": "publish", "timeout_seconds": 7},
            StepPolicy(timedelta(seconds=7), 5, timedelta(seconds=1)),
        ),
    ],
)
def test_a_steps_policy_is_what_the_dag_sets_and_the_kinds_default_for_the_rest(
    step: dict[str, Any], expected: StepPolicy
) -> None:
    assert step_policy(step) == expected


def test_the_policy_of_a_step_is_the_retry_policy_temporal_gets() -> None:
    retry = TWO_ATTEMPTS.retry_policy()

    assert retry.maximum_attempts == 2
    assert retry.initial_interval == timedelta(seconds=0.1)


def test_a_step_that_keeps_failing_names_the_step_the_attempts_and_the_agents_error() -> None:
    cause = ApplicationError("agent task failed: 429 Too Many Requests")
    error = _activity_error(cause, RetryState.MAXIMUM_ATTEMPTS_REACHED)

    failure = _failed("writer", TWO_ATTEMPTS, error)

    assert failure.step_id == "writer"
    assert failure.reason == (
        "step 'writer' failed after 2 attempts: agent task failed: 429 Too Many Requests"
    )
    assert "not valid JSON" not in failure.reason


def test_a_step_that_may_not_be_retried_fails_without_counting_attempts() -> None:
    cause = ApplicationError("Marketo reply has no receiptId", non_retryable=True)
    error = _activity_error(cause, RetryState.NON_RETRYABLE_FAILURE)

    assert _failed("publish", PUBLISH_DEFAULT, error).reason == (
        "step 'publish' failed: Marketo reply has no receiptId"
    )


def test_a_step_that_runs_too_long_says_how_long_and_how_many_attempts() -> None:
    cause = ActivityTimedOut(
        "timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]
    )
    policy = StepPolicy(timedelta(seconds=1), 1, timedelta(seconds=1))

    reason = _failed("writer", policy, _activity_error(cause, RetryState.TIMEOUT)).reason

    assert reason == "step 'writer' timed out after 1s (1 attempts)"


def test_an_error_that_is_not_an_activity_error_still_stops_the_run_naming_the_step() -> None:
    assert _as_step_failure("preview", RuntimeError("the database refused the write")).reason == (
        "step 'preview' failed: the database refused the write"
    )
    already = StepFailed("writer", "step 'writer' failed: x")
    assert _as_step_failure("preview", already) is already
    bookkeeping = _activity_error(ApplicationError("db down"), None)
    assert _as_step_failure("preview", bookkeeping).reason == "step 'preview' failed: db down"


def test_a_failed_agent_task_is_a_failed_call_and_gets_no_repair_message() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200, json=task_reply("429 Too Many Requests", state=invoker.TASK_FAILED)
        )

    async def ask() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            call = invoker.AgentCall("key", "write", {"type": "object"})
            await invoker.invoke(client, "http://agent.test", call)

    with pytest.raises(invoker.AgentCallFailed, match="429 Too Many Requests"):
        asyncio.run(ask())

    # One message, not the "fix your JSON" repair a bad reply gets: Temporal retries the step.
    assert len(sent) == 1
