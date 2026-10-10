from concurrent.futures import Executor

from ace_engine import db
from ace_engine.settings import TASK_QUEUE, Settings
from temporalio.client import Client
from temporalio.worker import Worker

from campaign_worker.activities import Activities
from campaign_worker.workflow import CampaignWorkflow


def build_worker(client: Client, settings: Settings, executor: Executor) -> Worker:
    activities = Activities(settings, db.make_engine(settings.database_url))
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CampaignWorkflow],
        activities=[
            activities.write_email_draft,
            activities.save_draft,
            activities.mark_failed,
        ],
        activity_executor=executor,
    )
