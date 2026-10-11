"""The campaign workflow on Temporal's time-skipping server with stub activities: a step
that fails with an activity error, not an agent or publish failure, while a sibling in its
wave still runs, stops the run with a reason naming that step. The cancelled sibling must
not hide the real error."""

import asyncio
import uuid
from typing import Any

from ace_engine.settings import TASK_QUEUE, WORKFLOW_NAME
from campaign_worker.workflow import CampaignWorkflow
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

DB_DOWN = "the database refused the write"
WAIT_SECONDS = 20
POLL_SECONDS = 0.05


class StubActivities:
    """The worker's activity names; mark_step fails when one step would succeed, the rest
    record calls. Failing on "succeeded", not "started", leaves the sibling approval time to
    open, so it is waiting on a human, not on an activity, when it is cancelled."""

    def __init__(self, failing_step: str) -> None:
        self.failing_step = failing_step
        self.failed: list[tuple[str, str]] = []

    @activity.defn(name="mark_step")
    async def mark_step(self, campaign_id: str, step_id: str, status: str) -> None:
        if step_id == self.failing_step and status == "succeeded":
            raise ApplicationError(DB_DOWN, non_retryable=True)

    @activity.defn(name="open_approval")
    async def open_approval(self, campaign_id: str) -> None:
        return None

    @activity.defn(name="mark_failed")
    async def mark_failed(self, campaign_id: str, step_id: str, reason: str) -> None:
        self.failed.append((step_id, reason))

    @activity.defn(name="finish_run")
    async def finish_run(self, campaign_id: str) -> None:
        return None


async def _run_until_failed(dag: dict[str, Any], stubs: StubActivities) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[CampaignWorkflow],
            activities=[stubs.mark_step, stubs.open_approval, stubs.mark_failed, stubs.finish_run],
        )
        async with worker:
            handle = await env.client.start_workflow(
                WORKFLOW_NAME,
                args=[str(uuid.uuid4()), "report", dag],
                id=f"campaign-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            for _ in range(int(WAIT_SECONDS / POLL_SECONDS)):
                if stubs.failed:
                    break
                await asyncio.sleep(POLL_SECONDS)
            # A failed run waits for a retry; one that ended on its own is already closed.
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate()


def test_activity_error_beside_a_waiting_sibling_stops_the_run_naming_the_step() -> None:
    # The approval comes first in the wave, so its cancellation is the first outcome.
    dag = {
        "steps": [{"id": "ok", "kind": "approval"}, {"id": "preview", "kind": "render"}],
        "edges": [],
    }
    stubs = StubActivities(failing_step="preview")

    asyncio.run(_run_until_failed(dag, stubs))

    assert len(stubs.failed) == 1, stubs.failed
    step_id, reason = stubs.failed[0]
    assert step_id == "preview"
    assert "'preview'" in reason and DB_DOWN in reason
