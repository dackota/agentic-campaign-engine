from concurrent.futures import Executor

from ace_engine import db
from ace_engine.settings import TASK_QUEUE, Settings
from temporalio.client import Client
from temporalio.worker import Worker

from campaign_worker.activities import Activities
from campaign_worker.workflow import CampaignWorkflow

DEFAULT_CACHED_WORKFLOWS = 1000


def build_worker(
    client: Client,
    settings: Settings,
    executor: Executor,
    *,
    max_cached_workflows: int = DEFAULT_CACHED_WORKFLOWS,
) -> Worker:
    activities = Activities(settings, db.make_engine(settings.database_url))
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[
            activities.write_email_draft,
            activities.save_draft,
            activities.mark_failed,
            activities.send_email,
            activities.mark_sent,
        ],
        activity_executor=executor,
        max_cached_workflows=max_cached_workflows,
    )
