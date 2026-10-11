"""The campaign workflow: a thin shell that follows the run's pinned workflow DAG.

Each wave starts every step whose parents have all succeeded, at the same time. Agent
steps draft the A/B emails, approval steps wait for a human, publish steps send only
after an approval (the API rejects a workflow where they would not), and wait steps
sleep.

Agent and publish steps take their timeout and retry policy from the DAG. A step that
fails past its retries stops the run with a reason naming the step; the run then waits
for the owner's retry-step signal and re-runs the steps of that wave not yet done."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ace_engine.settings import APPROVE_SIGNAL, RETRY_SIGNAL, WORKFLOW_NAME
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError, RetryState
from temporalio.exceptions import TimeoutError as ActivityTimedOut

with workflow.unsafe.imports_passed_through():
    from ace_engine import dag as graph
    from ace_engine.db import STEP_STARTED, STEP_SUCCEEDED

DB_STEP_TIMEOUT = timedelta(seconds=30)
DEFAULT_RETRY_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class StepPolicy:
    """How long one attempt of a step may run and how often it is tried."""

    timeout: timedelta
    maximum_attempts: int
    initial_interval: timedelta

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            maximum_attempts=self.maximum_attempts, initial_interval=self.initial_interval
        )


# The policy of a step whose DAG entry sets none, by kind.
DEFAULT_POLICIES = {
    graph.AGENT: StepPolicy(timedelta(minutes=5), 3, timedelta(seconds=1)),
    graph.PUBLISH: StepPolicy(timedelta(minutes=1), 5, timedelta(seconds=1)),
}


def step_policy(step: dict[str, Any]) -> StepPolicy:
    """The step's retry policy and timeout from the DAG, the kind's default where unset.
    The attempt limit comes from `retry.maximum_attempts`, else the builder's
    `max_attempts`, else the kind's default."""
    default = DEFAULT_POLICIES[step["kind"]]
    retry = step.get("retry", {})
    attempts = retry.get("maximum_attempts") or step.get("max_attempts")
    interval = retry.get("initial_interval_seconds")
    return StepPolicy(
        timeout=(
            timedelta(seconds=step["timeout_seconds"])
            if "timeout_seconds" in step
            else default.timeout
        ),
        maximum_attempts=attempts or default.maximum_attempts,
        initial_interval=(
            timedelta(seconds=interval) if interval is not None else default.initial_interval
        ),
    )


class StepFailed(Exception):
    def __init__(self, step_id: str, reason: str) -> None:
        super().__init__(reason)
        self.step_id = step_id
        self.reason = reason


def _failed(step_id: str, policy: StepPolicy, exc: ActivityError) -> StepFailed:
    """The step's failure with a reason that names the step and what went wrong."""
    cause = exc.cause
    attempts = policy.maximum_attempts
    if isinstance(cause, ActivityTimedOut):
        seconds = int(policy.timeout.total_seconds())
        return StepFailed(
            step_id, f"step {step_id!r} timed out after {seconds}s ({attempts} attempts)"
        )
    detail = cause.message if isinstance(cause, ApplicationError) else str(exc)
    if exc.retry_state == RetryState.MAXIMUM_ATTEMPTS_REACHED:
        return StepFailed(step_id, f"step {step_id!r} failed after {attempts} attempts: {detail}")
    return StepFailed(step_id, f"step {step_id!r} failed: {detail}")


def _is_cancellation(error: BaseException) -> bool:
    if isinstance(error, asyncio.CancelledError | CancelledError):
        return True
    return isinstance(error, ActivityError) and isinstance(error.cause, CancelledError)


def _as_step_failure(step_id: str, error: BaseException) -> StepFailed:
    """Any error a step raised, as a stop that names the step: an activity error from a
    bookkeeping call stops the run with a reason instead of failing the workflow."""
    if isinstance(error, StepFailed):
        return error
    if isinstance(error, ActivityError) and isinstance(error.cause, ApplicationError):
        return StepFailed(step_id, f"step {step_id!r} failed: {error.cause.message}")
    return StepFailed(step_id, f"step {step_id!r} failed: {error}")


@workflow.defn(name=WORKFLOW_NAME)
class CampaignWorkflow:
    def __init__(self) -> None:
        self._approvals = 0
        self._retries_asked = 0
        self._retries_used = 0
        self._outputs: dict[str, Any] = {}

    @workflow.signal(name=APPROVE_SIGNAL)
    def approve(self) -> None:
        self._approvals += 1

    @workflow.signal(name=RETRY_SIGNAL)
    def retry_step(self) -> None:
        self._retries_asked += 1

    @workflow.run
    async def run(self, campaign_id: str, report: str, dag: dict[str, Any]) -> None:
        done: frozenset[str] = frozenset()
        while wave := graph.ready_steps(dag, set(done)):
            # Approval steps that open together are settled by one approval.
            approvals_needed = self._approvals + 1
            succeeded, failure = await self._run_wave(
                campaign_id, report, dag, wave, approvals_needed
            )
            done = done | succeeded
            if failure is not None:
                # The run stops here; a retry re-runs the steps of this wave not yet done.
                await self._fail(campaign_id, failure)
                await self._until_retry_asked()
        await self._db("finish_run", campaign_id)

    async def _until_retry_asked(self) -> None:
        await workflow.wait_condition(lambda: self._retries_asked > self._retries_used)
        self._retries_used += 1

    async def _run_wave(
        self,
        campaign_id: str,
        report: str,
        dag: dict[str, Any],
        wave: list[dict[str, Any]],
        approvals_needed: int,
    ) -> tuple[frozenset[str], StepFailed | None]:
        """Run a wave's steps together. On the first failure, cancel the rest so a step
        waiting on a human cannot keep a failed run open. Returns the steps that succeeded
        and the failure that stopped the wave, if any."""
        tasks = [
            asyncio.ensure_future(self._step(campaign_id, report, dag, s, approvals_needed))
            for s in wave
        ]
        await workflow.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in tasks:
            if not task.done():
                task.cancel()
        # Await every task so a cancelled one finishes before the failure is recorded.
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        succeeded = frozenset(s["id"] for s, o in zip(wave, outcomes, strict=True) if o is None)
        # A step that failed on its own comes first; the cancelled ones are fallout, so they
        # never hide the real error, whatever their place in the wave.
        failures = [
            _as_step_failure(s["id"], o)
            for s, o in zip(wave, outcomes, strict=True)
            if isinstance(o, BaseException) and not _is_cancellation(o)
        ]
        if failures:
            return succeeded, failures[0]
        errors = [o for o in outcomes if isinstance(o, BaseException)]
        if errors:
            raise errors[0]
        return succeeded, None

    async def _db(self, activity: str, *args: Any) -> Any:
        return await workflow.execute_activity(
            activity, args=list(args), start_to_close_timeout=DB_STEP_TIMEOUT
        )

    async def _step(
        self,
        campaign_id: str,
        report: str,
        dag: dict[str, Any],
        step: dict[str, Any],
        approvals_needed: int,
    ) -> None:
        step_id, kind = step["id"], step["kind"]
        if kind == graph.AGENT:
            await self._agent(campaign_id, report, step)
        elif kind == graph.APPROVAL:
            await self._db("open_approval", campaign_id)
            await workflow.wait_condition(lambda: self._approvals >= approvals_needed)
            await self._db("mark_step", campaign_id, step_id, STEP_SUCCEEDED)
        elif kind == graph.PUBLISH:
            await self._publish(campaign_id, dag, step)
        elif kind == graph.WAIT:
            await self._db("mark_step", campaign_id, step_id, STEP_STARTED)
            await workflow.sleep(timedelta(seconds=step["duration_seconds"]))
            await self._db("mark_step", campaign_id, step_id, STEP_SUCCEEDED)
        elif kind == graph.RENDER:
            # The render service arrives in a later ticket; until then the step passes.
            await self._db("mark_step", campaign_id, step_id, STEP_STARTED)
            await self._db("mark_step", campaign_id, step_id, STEP_SUCCEEDED)
        else:
            raise StepFailed(step_id, f"step {step_id!r} has an unknown kind {kind!r}")

    async def _agent(self, campaign_id: str, report: str, step: dict[str, Any]) -> None:
        step_id, policy = step["id"], step_policy(step)
        try:
            drafts = await workflow.execute_activity(
                "write_email_draft",
                args=[campaign_id, report, step_id],
                start_to_close_timeout=policy.timeout,
                retry_policy=policy.retry_policy(),
            )
        except ActivityError as exc:
            raise _failed(step_id, policy, exc) from exc
        await self._db("save_agent_output", campaign_id, step_id, drafts)
        self._outputs[step_id] = drafts

    async def _publish(self, campaign_id: str, dag: dict[str, Any], step: dict[str, Any]) -> None:
        step_id, policy = step["id"], step_policy(step)
        source = graph.latest_ancestor_of_kind(dag, step_id, graph.AGENT)
        if source is None:
            raise StepFailed(step_id, f"publish step {step_id!r} has no agent step before it")
        await self._db("mark_step", campaign_id, step_id, STEP_STARTED)
        try:
            receipt = await workflow.execute_activity(
                "send_email",
                args=[campaign_id, self._outputs[source], step_id],
                start_to_close_timeout=policy.timeout,
                retry_policy=policy.retry_policy(),
            )
        except ActivityError as exc:
            raise _failed(step_id, policy, exc) from exc
        await self._db("mark_sent", campaign_id, step_id, receipt)

    async def _fail(self, campaign_id: str, failure: StepFailed) -> None:
        await self._db("mark_failed", campaign_id, failure.step_id, failure.reason)
