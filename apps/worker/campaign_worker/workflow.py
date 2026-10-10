"""The campaign workflow: a thin shell that asks the email writer for a draft."""

from datetime import timedelta

from ace_engine.settings import WORKFLOW_NAME
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

AGENT_STEP_TIMEOUT = timedelta(minutes=5)
DB_STEP_TIMEOUT = timedelta(seconds=30)
AGENT_RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name=WORKFLOW_NAME)
class CampaignWorkflow:
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
            cause = exc.cause
            reason = cause.message if isinstance(cause, ApplicationError) else str(exc)
            await workflow.execute_activity(
                "mark_failed",
                args=[campaign_id, reason],
                start_to_close_timeout=DB_STEP_TIMEOUT,
            )
            return
        await workflow.execute_activity(
            "save_draft",
            args=[campaign_id, draft],
            start_to_close_timeout=DB_STEP_TIMEOUT,
        )
