from concurrent.futures import Executor

from ace_engine import db, row_security, telemetry
from ace_engine.settings import TASK_QUEUE, Settings
from temporalio.client import Client
from temporalio.worker import Worker

from campaign_worker.activities import SERVICE, Activities
from campaign_worker.workflow import CampaignWorkflow

DEFAULT_CACHED_WORKFLOWS = 1000


def build_worker(
    client: Client,
    settings: Settings,
    executor: Executor,
    *,
    max_cached_workflows: int = DEFAULT_CACHED_WORKFLOWS,
) -> Worker:
    telemetry.configure(SERVICE)
    telemetry.instrument_httpx()
    engine = db.make_engine(settings.database_url)
    # The step cache reads as the campaign's team, so the team role and its policies must
    # exist even when the worker starts before the API.
    row_security.install(engine)
    activities = Activities(settings, engine)
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
            activities.pause_for_budget,
            activities.resume_after_budget,
            activities.finish_run,
            activities.send_email,
            activities.mark_sent,
            activities.announce_approval,
            activities.announce_published,
            activities.publish_content,
            activities.save_cards,
        ],
        activity_executor=executor,
        max_cached_workflows=max_cached_workflows,
    )
