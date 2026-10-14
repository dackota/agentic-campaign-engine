"""The campaign workflow on Temporal's time-skipping server with stub activities: no database,
no agent, no network. `StubActivities` answers every activity the workflow calls and records
the calls in order; `run_workflow` runs a DAG on them until the run ends or stops with a
reason."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from ace_engine.settings import TASK_QUEUE, WORKFLOW_NAME
from campaign_worker.publisher import PUBLISH_STEP
from campaign_worker.workflow import CampaignWorkflow
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

WAIT_SECONDS = 30
# The test server can drop a workflow task when an activity result and the workflow's cancel of
# that activity cross; the task is then retried after this long, not the default 10 seconds.
WORKFLOW_TASK_TIMEOUT = timedelta(seconds=1)
POLL_SECONDS = 0.02
FINISHED = "finished"
FAILED = "failed"

AgentBehavior = Callable[[str], Awaitable[dict[str, Any]]]
Drive = Callable[[WorkflowEnvironment, WorkflowHandle[Any, Any], "StubActivities"], Awaitable[None]]


class StubActivities:
    """Every activity of the worker, by name. `calls` holds (activity, args) in the order
    they ran; `agent` decides what an agent step returns or raises, and the first `slot_refusals`
    claims of a team slot are refused."""

    def __init__(self, agent: AgentBehavior | None = None, slot_refusals: int = 0) -> None:
        self.slot_refusals = slot_refusals
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.failed = asyncio.Event()
        self._agent = agent

    def called(self, name: str) -> list[tuple[object, ...]]:
        return [args for called, args in self.calls if called == name]

    def activities(self) -> list[Callable[..., Any]]:
        return [
            self.mark_step,
            self.open_approval,
            self.announce_approval,
            self.claim_step_slot,
            self.release_step_slot,
            self.run_agent_step,
            self.save_agent_output,
            self.save_cards,
            self.record_scores,
            self.send_email,
            self.publish_content,
            self.mark_sent,
            self.announce_published,
            self.mark_failed,
            self.finish_run,
        ]

    def _log(self, name: str, *args: object) -> None:
        self.calls.append((name, args))

    @activity.defn(name="mark_step")
    async def mark_step(self, campaign_id: str, step_id: str, status: str) -> None:
        self._log("mark_step", step_id, status)

    @activity.defn(name="open_approval")
    async def open_approval(self, campaign_id: str) -> None:
        self._log("open_approval")

    @activity.defn(name="announce_approval")
    async def announce_approval(self, campaign_id: str) -> None:
        self._log("announce_approval")

    @activity.defn(name="claim_step_slot")
    async def claim_step_slot(self, campaign_id: str, key: str, lease_seconds: float) -> bool:
        self._log("claim_step_slot", key)
        refused = len(self.called("claim_step_slot")) <= self.slot_refusals
        return not refused

    @activity.defn(name="release_step_slot")
    async def release_step_slot(self, key: str) -> None:
        self._log("release_step_slot", key)

    @activity.defn(name="run_agent_step")
    async def run_agent_step(
        self,
        campaign_id: str,
        report: str,
        step_id: str,
        context: dict[str, Any],
        review_rounds: int = 0,
    ) -> dict[str, Any]:
        self._log("run_agent_step", step_id)
        if self._agent is not None:
            return await self._agent(step_id)
        return {"output": [{"step": step_id}], "session": f"session-{step_id}", "usage": {}}

    @activity.defn(name="save_agent_output")
    async def save_agent_output(
        self, campaign_id: str, step_id: str, result: dict[str, Any]
    ) -> None:
        self._log("save_agent_output", step_id)

    @activity.defn(name="save_cards")
    async def save_cards(self, campaign_id: str, output: dict[str, Any]) -> None:
        self._log("save_cards")

    @activity.defn(name="record_scores")
    async def record_scores(
        self, campaign_id: str, step_id: str, assets: list[str], output: dict[str, Any]
    ) -> list[str]:
        self._log("record_scores", tuple(assets))
        return []

    @activity.defn(name="send_email")
    async def send_email(
        self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str = PUBLISH_STEP
    ) -> str:
        self._log("send_email", step_id)
        return f"receipt-{step_id}"

    @activity.defn(name="publish_content")
    async def publish_content(
        self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str = PUBLISH_STEP
    ) -> None:
        self._log("publish_content", step_id)

    @activity.defn(name="mark_sent")
    async def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> None:
        self._log("mark_sent", step_id, receipt)

    @activity.defn(name="announce_published")
    async def announce_published(self, campaign_id: str, receipt: str) -> None:
        self._log("announce_published", receipt)

    @activity.defn(name="mark_failed")
    async def mark_failed(self, campaign_id: str, step_id: str, reason: str) -> None:
        self._log("mark_failed", step_id, reason)
        self.failed.set()

    @activity.defn(name="finish_run")
    async def finish_run(self, campaign_id: str) -> None:
        self._log("finish_run")


@asynccontextmanager
async def time_skipping_env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def until(condition: Callable[[], bool]) -> None:
    """Wait (in real time, so activities can run) until `condition` holds."""
    for _ in range(int(WAIT_SECONDS / POLL_SECONDS)):
        if condition():
            return
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError("the condition never held")


async def run_workflow(
    env: WorkflowEnvironment,
    dag: dict[str, Any],
    stubs: StubActivities,
    drive: Drive | None = None,
) -> str:
    """Run `dag` as the campaign workflow on `stubs`. `drive` may signal the run while it
    goes and must return before the run is awaited. Returns FINISHED when the workflow
    ended and FAILED when it stopped with a reason (a failed run waits for a retry, so it
    is terminated here)."""
    queue = f"{TASK_QUEUE}-{uuid.uuid4().hex}"
    async with Worker(
        env.client, task_queue=queue, workflows=[CampaignWorkflow], activities=stubs.activities()
    ):
        handle = await env.client.start_workflow(
            WORKFLOW_NAME,
            args=[str(uuid.uuid4()), "a report", dag],
            id=f"campaign-{uuid.uuid4()}",
            task_queue=queue,
            task_timeout=WORKFLOW_TASK_TIMEOUT,
        )
        ended = stopped = None
        try:
            if drive is not None:
                await asyncio.wait_for(drive(env, handle, stubs), WAIT_SECONDS)
            # Awaiting the result lets the time-skipping server skip a wait step's time, so
            # it is left until the driver is done: a run held for a human would skip to its end.
            ended = asyncio.ensure_future(handle.result())
            stopped = asyncio.ensure_future(stubs.failed.wait())
            await asyncio.wait(
                {ended, stopped}, return_when=asyncio.FIRST_COMPLETED, timeout=WAIT_SECONDS
            )
            # A run that stopped waits for a retry, and awaiting it lets the time-skipping
            # server skip to its timeout: a stop counts before that timeout does.
            if stubs.failed.is_set():
                return FAILED
            assert ended.done(), "the run neither ended nor stopped"
            ended.result()
            return FINISHED
        finally:
            # Close the run, then let the result wait end by itself: cancelling it midway
            # leaves the server's time skipping unlocked for the cases that follow.
            with contextlib.suppress(RPCError):  # already closed: the run ended on its own
                await handle.terminate()
            if stopped is not None:
                stopped.cancel()
            waits = [t for t in (ended, stopped) if t is not None]
            await asyncio.gather(*waits, return_exceptions=True)
