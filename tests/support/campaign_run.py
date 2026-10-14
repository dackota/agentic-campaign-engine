"""The real CampaignWorkflow on Temporal's time-skipping server, with stub activities.

`StubActivities` registers every activity the workflow calls under its real name. Each one
records its call and gives a quiet answer (a step that succeeds, a free team slot, a receipt);
a test passes a handler for the activity whose behaviour it is about. No database, no agent,
no network: a sleep or a retry wait in the workflow costs no real time.
"""

import asyncio
import contextlib
import inspect
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ace_engine.settings import (
    APPROVE_SIGNAL,
    RAISE_BUDGET_SIGNAL,
    RETRY_SIGNAL,
    TASK_QUEUE,
    WORKFLOW_NAME,
)
from campaign_worker.activities import RedoJob
from campaign_worker.workflow import CampaignWorkflow
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

WAIT_SECONDS = 20
POLL_SECONDS = 0.02
RECEIPT = "receipt-1"
# What a stub agent step answers: the two emails an A/B writer makes, so a publish step can
# send it. A test that needs another shape passes its own `run_agent_step`.
MODEL = "scripted-model"

Handler = Callable[..., object]


class StubActivities:
    """Every activity of the workflow, recording `(name, args)` in `calls`. `handlers` maps an
    activity name to a function of its arguments (sync or async) that replaces the quiet
    answer, and may raise `ApplicationError` to fail the activity."""

    def __init__(self, **handlers: Handler) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._handlers = handlers

    def args_of(self, name: str) -> list[tuple[object, ...]]:
        """The arguments of every call of the activity `name`, in order."""
        return [args for called, args in self.calls if called == name]

    def count(self, name: str) -> int:
        return len(self.args_of(name))

    async def _answer(self, name: str, args: tuple[object, ...], quiet: object) -> object:
        self.calls.append((name, args))
        handler = self._handlers.get(name)
        if handler is None:
            return quiet
        answer = handler(*args)
        return await answer if inspect.isawaitable(answer) else answer

    @property
    def activities(self) -> list[Callable[..., object]]:
        return [
            self.mark_step,
            self.open_approval,
            self.announce_approval,
            self.announce_published,
            self.run_agent_step,
            self.save_agent_output,
            self.record_scores,
            self.redo_asset,
            self.save_cards,
            self.claim_step_slot,
            self.release_step_slot,
            self.pause_for_budget,
            self.resume_after_budget,
            self.send_email,
            self.publish_content,
            self.mark_sent,
            self.mark_failed,
            self.finish_run,
        ]

    @activity.defn(name="mark_step")
    async def mark_step(self, campaign_id: str, step_id: str, status: str) -> object:
        return await self._answer("mark_step", (campaign_id, step_id, status), None)

    @activity.defn(name="open_approval")
    async def open_approval(self, campaign_id: str) -> object:
        return await self._answer("open_approval", (campaign_id,), None)

    @activity.defn(name="announce_approval")
    async def announce_approval(self, campaign_id: str) -> object:
        return await self._answer("announce_approval", (campaign_id,), None)

    @activity.defn(name="announce_published")
    async def announce_published(self, campaign_id: str, receipt: str) -> object:
        return await self._answer("announce_published", (campaign_id, receipt), None)

    @activity.defn(name="run_agent_step")
    async def run_agent_step(
        self,
        campaign_id: str,
        report: str,
        step_id: str,
        context: dict[str, Any],
        review_rounds: int = 0,
    ) -> object:
        quiet = {
            "output": [{"step": step_id}, {"step": step_id}],
            "session": f"session-{step_id}",
            "usage": {"model": MODEL, "input_tokens": 1, "output_tokens": 1},
        }
        args = (campaign_id, report, step_id, context, review_rounds)
        return await self._answer("run_agent_step", args, quiet)

    @activity.defn(name="save_agent_output")
    async def save_agent_output(
        self, campaign_id: str, step_id: str, result: dict[str, Any]
    ) -> object:
        return await self._answer("save_agent_output", (campaign_id, step_id, result), None)

    @activity.defn(name="record_scores")
    async def record_scores(
        self, campaign_id: str, step_id: str, assets: list[str], output: dict[str, Any]
    ) -> object:
        return await self._answer("record_scores", (campaign_id, step_id, assets, output), [])

    @activity.defn(name="redo_asset")
    async def redo_asset(self, job: RedoJob) -> object:
        quiet = {"output": [{"step": job.step_id, "redone": True}] * 2}
        return await self._answer("redo_asset", (job,), quiet)

    @activity.defn(name="save_cards")
    async def save_cards(self, campaign_id: str, output: dict[str, Any]) -> object:
        return await self._answer("save_cards", (campaign_id, output), None)

    @activity.defn(name="claim_step_slot")
    async def claim_step_slot(self, campaign_id: str, key: str, lease_seconds: float) -> object:
        return await self._answer("claim_step_slot", (campaign_id, key, lease_seconds), True)

    @activity.defn(name="release_step_slot")
    async def release_step_slot(self, key: str) -> object:
        return await self._answer("release_step_slot", (key,), None)

    @activity.defn(name="pause_for_budget")
    async def pause_for_budget(self, campaign_id: str) -> object:
        return await self._answer("pause_for_budget", (campaign_id,), None)

    @activity.defn(name="resume_after_budget")
    async def resume_after_budget(self, campaign_id: str) -> object:
        return await self._answer("resume_after_budget", (campaign_id,), None)

    @activity.defn(name="send_email")
    async def send_email(
        self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str = "publish"
    ) -> object:
        return await self._answer("send_email", (campaign_id, drafts, step_id), RECEIPT)

    @activity.defn(name="publish_content")
    async def publish_content(
        self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str = "publish"
    ) -> object:
        return await self._answer("publish_content", (campaign_id, drafts, step_id), None)

    @activity.defn(name="mark_sent")
    async def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> object:
        return await self._answer("mark_sent", (campaign_id, step_id, receipt), None)

    @activity.defn(name="mark_failed")
    async def mark_failed(self, campaign_id: str, step_id: str, reason: str) -> object:
        return await self._answer("mark_failed", (campaign_id, step_id, reason), None)

    @activity.defn(name="finish_run")
    async def finish_run(self, campaign_id: str) -> object:
        return await self._answer("finish_run", (campaign_id,), None)


@dataclass(frozen=True)
class Run:
    """A started campaign workflow and the stubs it runs on."""

    env: WorkflowEnvironment
    handle: WorkflowHandle[Any, None]
    stubs: StubActivities

    async def until(self, name: str, times: int = 1) -> None:
        """Wait until the activity `name` has been called `times` times."""
        for _ in range(int(WAIT_SECONDS / POLL_SECONDS)):
            if self.stubs.count(name) >= times:
                return
            await asyncio.sleep(POLL_SECONDS)
        raise AssertionError(
            f"{name} was called {self.stubs.count(name)} times: {self.stubs.calls}"
        )

    async def sleep(self, duration: timedelta) -> None:
        """Let the workflow's clock run on by `duration`, in no real time."""
        await self.env.sleep(duration)

    async def approve(self) -> None:
        await self.handle.signal(APPROVE_SIGNAL)

    async def raise_budget(self) -> None:
        await self.handle.signal(RAISE_BUDGET_SIGNAL)

    async def retry_step(self) -> None:
        await self.handle.signal(RETRY_SIGNAL)

    async def finish(self) -> None:
        """Wait for the run to end on its own."""
        await asyncio.wait_for(self.handle.result(), WAIT_SECONDS)


@asynccontextmanager
async def running_campaign(
    dag: dict[str, Any], stubs: StubActivities, report: str = "report"
) -> AsyncIterator[Run]:
    """Start the workflow on `dag`; stop it when the block ends if it is still waiting (a
    failed run waits for a retry, an approval waits for a human)."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[CampaignWorkflow],
            activities=stubs.activities,
        )
        async with worker:
            handle = await env.client.start_workflow(
                WORKFLOW_NAME,
                args=[str(uuid.uuid4()), report, dag],
                id=f"campaign-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            try:
                yield Run(env, handle, stubs)
            finally:
                if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                    with contextlib.suppress(RPCError):  # it closed between the check and now
                        await handle.terminate()
