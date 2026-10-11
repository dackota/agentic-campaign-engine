from concurrent.futures import Executor

from ace_engine import db, telemetry
from ace_engine.settings import TASK_QUEUE, Settings
from temporalio.client import Client
from temporalio.worker import Worker

from campaign_worker.activities import Activities
from campaign_worker.workflow import CampaignWorkflow

DEFAULT_CACHED_WORKFLOWS = 1000
SERVICE = "campaign-worker"


def build_worker(
    client: Client,
    settings: Settings,
    executor: Executor,
    *,
    max_cached_workflows: int = DEFAULT_CACHED_WORKFLOWS,
) -> Worker:
    telemetry.configure(SERVICE)
    telemetry.instrument_httpx()
    activities = Activities(settings, db.make_engine(settings.database_url))
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[
            activities.run_agent_step,
            activities.save_agent_output,
            activities.mark_step,
            activities.open_approval,
            activities.mark_failed,
            activities.finish_run,
            activities.send_email,
            activities.mark_sent,
            activities.announce_approval,
            activities.announce_published,
            activities.publish_content,
        ],
        activity_executor=executor,
        max_cached_workflows=max_cached_workflows,
    )
