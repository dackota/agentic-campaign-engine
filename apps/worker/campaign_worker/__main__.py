"""Run the campaign worker: `python -m campaign_worker`. Settings come from `ACE_*`
variables. SIGTERM (a pod stopping) and SIGINT (the dev file watcher) stop it cleanly."""

import asyncio
import logging
import os
import signal
from concurrent.futures import ThreadPoolExecutor

from ace_engine import telemetry
from ace_engine.env import settings_from_env
from ace_engine.settings import Settings
from temporalio.client import Client

from campaign_worker.worker import build_worker

ACTIVITY_THREADS = 8

log = logging.getLogger("campaign_worker")


async def run(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        interceptors=telemetry.temporal_interceptors(),
    )
    with ThreadPoolExecutor(max_workers=ACTIVITY_THREADS) as executor:
        async with build_worker(client, settings, executor):
            log.info("worker polling task queue")
            await stop.wait()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(settings_from_env(os.environ, is_api=False)))


if __name__ == "__main__":
    main()
