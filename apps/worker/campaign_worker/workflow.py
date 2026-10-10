"""The campaign workflow: a thin shell that follows the run's pinned workflow DAG.

Each wave starts every step whose parents have all succeeded, at the same time. Agent
steps draft the A/B emails, approval steps wait for a human, publish steps send only
after an approval (the API rejects a workflow where they would not), and wait steps
sleep."""

import asyncio
from datetime import timedelta
from typing import Any

from ace_engine.settings import APPROVE_SIGNAL, WORKFLOW_NAME
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from ace_engine import dag as graph
    from ace_engine.db import STEP_STARTED, STEP_SUCCEEDED

AGENT_STEP_TIMEOUT = timedelta(minutes=5)
DB_STEP_TIMEOUT = timedelta(seconds=30)
SEND_STEP_TIMEOUT = timedelta(minutes=1)
AGENT_RETRY = RetryPolicy(maximum_attempts=3)
SEND_RETRY = RetryPolicy(maximum_attempts=5)


class StepFailed(Exception):
    def __init__(self, step_id: str, reason: str) -> None:
        super().__init__(reason)
        self.step_id = step_id
        self.reason = reason


def _reason(exc: ActivityError) -> str:
    cause = exc.cause
    return cause.message if isinstance(cause, ApplicationError) else str(exc)


@workflow.defn(name=WORKFLOW_NAME)
class CampaignWorkflow:
    def __init__(self) -> None:
        self._approvals = 0
        self._outputs: dict[str, Any] = {}

    @workflow.signal(name=APPROVE_SIGNAL)
    def approve(self) -> None:
        self._approvals += 1

    @workflow.run
    async def run(self, campaign_id: str, report: str, dag: dict[str, Any]) -> None:
        done: set[str] = set()
        while wave := graph.ready_steps(dag, done):
            # Approval steps that open together are settled by one approval.
            approvals_needed = self._approvals + 1
            results = await self._run_wave(campaign_id, report, dag, wave, approvals_needed)
            for result in results:
                if isinstance(result, StepFailed):
                    await self._fail(campaign_id, result)
                    return
                if isinstance(result, BaseException):
                    raise result
            done.update(s["id"] for s in wave)
        await self._db("finish_run", campaign_id)

    async def _run_wave(
        self,
        campaign_id: str,
        report: str,
        dag: dict[str, Any],
        wave: list[dict[str, Any]],
        approvals_needed: int,
    ) -> list[Any]:
        """Run a wave's steps together. On the first failure, cancel the rest so a step
        waiting on a human cannot keep a failed run open. Returns each step's outcome."""
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
        # A step that failed on its own comes first; the cancelled ones are fallout.
        failures = [o for o in outcomes if isinstance(o, StepFailed)]
        return failures or outcomes

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
            await self._agent(campaign_id, report, step_id)
        elif kind == graph.APPROVAL:
            await self._db("open_approval", campaign_id)
            await workflow.wait_condition(lambda: self._approvals >= approvals_needed)
            await self._db("mark_step", campaign_id, step_id, STEP_SUCCEEDED)
        elif kind == graph.PUBLISH:
            await self._publish(campaign_id, dag, step_id)
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

    async def _agent(self, campaign_id: str, report: str, step_id: str) -> None:
        try:
            drafts = await workflow.execute_activity(
                "write_email_draft",
                args=[campaign_id, report, step_id],
                start_to_close_timeout=AGENT_STEP_TIMEOUT,
                retry_policy=AGENT_RETRY,
            )
        except ActivityError as exc:
            raise StepFailed(step_id, _reason(exc)) from exc
        await self._db("save_agent_output", campaign_id, step_id, drafts)
        self._outputs[step_id] = drafts

    async def _publish(self, campaign_id: str, dag: dict[str, Any], step_id: str) -> None:
        source = graph.latest_ancestor_of_kind(dag, step_id, graph.AGENT)
        if source is None:
            raise StepFailed(step_id, f"publish step {step_id!r} has no agent step before it")
        await self._db("mark_step", campaign_id, step_id, STEP_STARTED)
        try:
            receipt = await workflow.execute_activity(
                "send_email",
                args=[campaign_id, self._outputs[source]],
                start_to_close_timeout=SEND_STEP_TIMEOUT,
                retry_policy=SEND_RETRY,
            )
        except ActivityError as exc:
            raise StepFailed(step_id, _reason(exc)) from exc
        await self._db("mark_sent", campaign_id, step_id, receipt)

    async def _fail(self, campaign_id: str, failure: StepFailed) -> None:
        await self._db("mark_failed", campaign_id, failure.step_id, failure.reason)
