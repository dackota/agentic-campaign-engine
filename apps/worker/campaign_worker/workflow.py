"""The campaign workflow: a thin shell that drafts an email, waits for a human to approve
it, and only then sends it."""

from datetime import timedelta

from ace_engine.settings import APPROVE_SIGNAL, WORKFLOW_NAME
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

AGENT_STEP_TIMEOUT = timedelta(minutes=5)
DB_STEP_TIMEOUT = timedelta(seconds=30)
SEND_STEP_TIMEOUT = timedelta(minutes=1)
AGENT_RETRY = RetryPolicy(maximum_attempts=3)
SEND_RETRY = RetryPolicy(maximum_attempts=5)


@workflow.defn(name=WORKFLOW_NAME)
class CampaignWorkflow:
    def __init__(self) -> None:
        self._approved = False

    @workflow.signal(name=APPROVE_SIGNAL)
    def approve(self) -> None:
        self._approved = True

    @workflow.run
    async def run(self, campaign_id: str, report: str) -> None:
        try:
            draft = await workflow.execute_activity(
                "write_email_draft",
                args=[campaign_id, report],
                start_to_close_timeout=AGENT_STEP_TIMEOUT,
                retry_policy=AGENT_RETRY,
            )
        except ActivityError as exc:
            await self._fail(campaign_id, exc)
            return
        await workflow.execute_activity(
            "save_draft",
            args=[campaign_id, draft],
            start_to_close_timeout=DB_STEP_TIMEOUT,
        )
        await workflow.wait_condition(lambda: self._approved)
        try:
            receipt = await workflow.execute_activity(
                "send_email",
                args=[campaign_id, draft],
                start_to_close_timeout=SEND_STEP_TIMEOUT,
                retry_policy=SEND_RETRY,
            )
        except ActivityError as exc:
            await self._fail(campaign_id, exc)
            return
        await workflow.execute_activity(
            "mark_sent",
            args=[campaign_id, receipt],
            start_to_close_timeout=DB_STEP_TIMEOUT,
        )

    async def _fail(self, campaign_id: str, exc: ActivityError) -> None:
        cause = exc.cause
        reason = cause.message if isinstance(cause, ApplicationError) else str(exc)
        await workflow.execute_activity(
            "mark_failed",
            args=[campaign_id, reason],
            start_to_close_timeout=DB_STEP_TIMEOUT,
        )
