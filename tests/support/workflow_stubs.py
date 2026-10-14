"""The campaign workflow on Temporal's time-skipping server with stub activities that record
their calls: a test reads which activities the workflow ran, in what order, with what
arguments, and sets what they answer. No database, agent or network."""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from ace_engine.settings import APPROVE_SIGNAL, TASK_QUEUE, WORKFLOW_NAME
from campaign_worker.activities import RedoJob
from campaign_worker.workflow import CampaignWorkflow
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

POLL_SECONDS = 0.05
WAIT_SECONDS = 20
# The activities after which the run is over: it finished, or it stopped and waits for a retry.
ENDING = ("finish_run", "mark_failed")


@dataclass
class StubActivities:
    """Every activity the workflow calls. An agent step answers `agent_outputs[step]` (a
    marker dict by default); `record_scores` answers `score_reasons`; `send_email` answers
    `receipt`."""

    agent_outputs: dict[str, Any] = field(default_factory=dict)
    score_reasons: list[str] = field(default_factory=list)
    receipt: str = "receipt-1"
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def called(self, name: str) -> list[tuple[object, ...]]:
        return [args for n, args in self.calls if n == name]

    def is_over(self) -> bool:
        return any(name in ENDING for name in self.names())

    def _record(self, name: str, *args: object) -> None:
        self.calls.append((name, args))

    @activity.defn(name="run_agent_step")
    async def run_agent_step(
        self, campaign_id: str, report: str, step_id: str, context: dict[str, Any], rounds: int
    ) -> dict[str, Any]:
        self._record("run_agent_step", campaign_id, report, step_id, context, rounds)
        output = self.agent_outputs.get(step_id, {"made_by": step_id})
        return {"output": output, "session": f"session-{step_id}"}

    @activity.defn(name="save_agent_output")
    async def save_agent_output(
        self, campaign_id: str, step_id: str, result: dict[str, Any]
    ) -> None:
        self._record("save_agent_output", campaign_id, step_id, result)

    @activity.defn(name="record_scores")
    async def record_scores(
        self, campaign_id: str, step_id: str, assets: list[str], output: dict[str, Any]
    ) -> list[str]:
        self._record("record_scores", campaign_id, step_id, assets, output)
        return self.score_reasons

    @activity.defn(name="redo_asset")
    async def redo_asset(self, job: RedoJob) -> dict[str, Any]:
        self._record("redo_asset", job)
        return {"output": self.agent_outputs.get(job.step_id, {"redone": job.step_id})}

    @activity.defn(name="save_cards")
    async def save_cards(self, campaign_id: str, output: object) -> None:
        self._record("save_cards", campaign_id, output)

    @activity.defn(name="mark_step")
    async def mark_step(self, campaign_id: str, step_id: str, status: str) -> None:
        self._record("mark_step", campaign_id, step_id, status)

    @activity.defn(name="claim_step_slot")
    async def claim_step_slot(self, campaign_id: str, key: str, lease_seconds: float) -> bool:
        self._record("claim_step_slot", campaign_id, key)
        return True

    @activity.defn(name="release_step_slot")
    async def release_step_slot(self, key: str) -> None:
        self._record("release_step_slot", key)

    @activity.defn(name="open_approval")
    async def open_approval(self, campaign_id: str) -> None:
        self._record("open_approval", campaign_id)

    @activity.defn(name="mark_failed")
    async def mark_failed(self, campaign_id: str, step_id: str, reason: str) -> None:
        self._record("mark_failed", campaign_id, step_id, reason)

    @activity.defn(name="pause_for_budget")
    async def pause_for_budget(self, campaign_id: str) -> None:
        self._record("pause_for_budget", campaign_id)

    @activity.defn(name="resume_after_budget")
    async def resume_after_budget(self, campaign_id: str) -> None:
        self._record("resume_after_budget", campaign_id)

    @activity.defn(name="finish_run")
    async def finish_run(self, campaign_id: str) -> None:
        self._record("finish_run", campaign_id)

    @activity.defn(name="send_email")
    async def send_email(self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str) -> str:
        self._record("send_email", campaign_id, drafts, step_id)
        return self.receipt

    @activity.defn(name="publish_content")
    async def publish_content(
        self, campaign_id: str, drafts: list[dict[str, Any]], step_id: str
    ) -> None:
        self._record("publish_content", campaign_id, drafts, step_id)

    @activity.defn(name="mark_sent")
    async def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> None:
        self._record("mark_sent", campaign_id, step_id, receipt)

    @activity.defn(name="announce_approval")
    async def announce_approval(self, campaign_id: str) -> None:
        self._record("announce_approval", campaign_id)

    @activity.defn(name="announce_published")
    async def announce_published(self, campaign_id: str, receipt: str) -> None:
        self._record("announce_published", campaign_id, receipt)

    def all(self) -> list[Any]:
        return [
            self.run_agent_step,
            self.save_agent_output,
            self.record_scores,
            self.redo_asset,
            self.save_cards,
            self.mark_step,
            self.claim_step_slot,
            self.release_step_slot,
            self.open_approval,
            self.mark_failed,
            self.pause_for_budget,
            self.resume_after_budget,
            self.finish_run,
            self.send_email,
            self.publish_content,
            self.mark_sent,
            self.announce_approval,
            self.announce_published,
        ]


async def _run(dag: dict[str, Any], stubs: StubActivities, report: str, approves: bool) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client, task_queue=TASK_QUEUE, workflows=[CampaignWorkflow], activities=stubs.all()
        ):
            handle = await env.client.start_workflow(
                WORKFLOW_NAME,
                args=[str(uuid.uuid4()), report, dag],
                id=f"campaign-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            approved = 0
            for _ in range(int(WAIT_SECONDS / POLL_SECONDS)):
                if stubs.is_over():
                    break
                if approves and len(stubs.called("open_approval")) > approved:
                    approved += 1
                    await handle.signal(APPROVE_SIGNAL)
                await asyncio.sleep(POLL_SECONDS)
            # A stopped run waits for a retry; a finished one is already closed.
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate()


def run_campaign(
    dag: dict[str, Any], stubs: StubActivities, *, report: str = "report", approves: bool = True
) -> StubActivities:
    """Run `dag` on the workflow until it finishes or stops on a failure. An approval step
    is approved as soon as it opens, unless `approves` is False. Returns `stubs`, which hold
    what the workflow called."""
    asyncio.run(_run(dag, stubs, report, approves))
    return stubs
