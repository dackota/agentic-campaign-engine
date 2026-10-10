"""Seam 1 harness: real Postgres, Temporal's time-skipping test server, the scripted
A2A agent, the worker, and the Campaign API, started together on free local ports.

One setting (`ACE_DEPTH`, read by `Depth.from_env`) picks fast or live depth. Live depth
is wired in a later ticket, so starting a live stack raises.
"""

import asyncio
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType

import uvicorn
from temporalio.testing import WorkflowEnvironment
from testcontainers.community.postgres import PostgresContainer

from tests.harness.scripted_agent import ScriptedAgent

POSTGRES_IMAGE = "postgres:16-alpine"
START_TIMEOUT_SECONDS = 180
STOP_TIMEOUT_SECONDS = 60
WORKER_THREADS = 8
# Temporal's test server never falls back from a stopped worker's sticky queue, so a
# restarted worker would wait forever. No cache means every task replays from history.
NO_WORKFLOW_CACHE = 0
STARTUP_POLLS = 600
STARTUP_POLL_SECONDS = 0.1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Stack:
    def __init__(self, depth: str | None = None, api_port: int | None = None) -> None:
        from ace_engine.settings import Depth

        self.depth = Depth.parse(depth) if depth is not None else Depth.from_env()
        self.agent = ScriptedAgent()
        self.api_port = api_port or free_port()
        self.marketo_port = free_port()
        self._restart_requested: asyncio.Event | None = None
        self._restarted = threading.Event()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._postgres: PostgresContainer | None = None

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def marketo_url(self) -> str:
        return f"http://127.0.0.1:{self.marketo_port}"

    def restart_worker(self) -> None:
        """Stop the worker and start a fresh one; the workflow resumes by replay."""
        assert self._loop is not None and self._restart_requested is not None
        self._restarted.clear()
        self._loop.call_soon_threadsafe(self._restart_requested.set)
        if not self._restarted.wait(START_TIMEOUT_SECONDS):
            raise RuntimeError("worker did not restart")

    def start(self) -> "Stack":
        from ace_engine.settings import Depth

        if self.depth is Depth.LIVE:
            raise NotImplementedError("live depth is wired in a later ticket")
        self._postgres = PostgresContainer(POSTGRES_IMAGE, driver="psycopg")
        self._postgres.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_SECONDS) or self._error is not None:
            self.stop()
            raise RuntimeError(f"stack did not start: {self._error!r}")
        return self

    def stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=STOP_TIMEOUT_SECONDS)
        if self._postgres is not None:
            self._postgres.stop()
            self._postgres = None

    def __enter__(self) -> "Stack":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:  # surfaced to start()
            self._error = exc
            self._ready.set()

    async def _main(self) -> None:
        from ace_engine.settings import Settings
        from campaign_api.main import create_app
        from campaign_worker.worker import build_worker
        from fake_marketo.app import create_app as create_marketo

        assert self._postgres is not None
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._restart_requested = asyncio.Event()
        agent_port = free_port()
        env = await WorkflowEnvironment.start_time_skipping()
        try:
            settings = Settings(
                depth=self.depth,
                database_url=self._postgres.get_connection_url(),
                temporal_address=env.client.service_client.config.target_host,
                temporal_namespace=env.client.namespace,
                agent_url=f"http://127.0.0.1:{agent_port}",
                marketo_url=self.marketo_url,
            )
            servers = [
                uvicorn.Server(
                    uvicorn.Config(
                        self.agent.app, port=agent_port, host="127.0.0.1", log_level="warning"
                    )
                ),
                uvicorn.Server(
                    uvicorn.Config(
                        create_marketo(),
                        port=self.marketo_port,
                        host="127.0.0.1",
                        log_level="warning",
                    )
                ),
                uvicorn.Server(
                    uvicorn.Config(
                        create_app(settings),
                        port=self.api_port,
                        host="127.0.0.1",
                        log_level="warning",
                    )
                ),
            ]
            tasks = [asyncio.create_task(s.serve()) for s in servers]
            with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
                await self._wait_started(servers)
                first = True
                while not self._stop.is_set():
                    worker = build_worker(
                        env.client, settings, executor, max_cached_workflows=NO_WORKFLOW_CACHE
                    )
                    async with worker:
                        if first:
                            self._ready.set()
                            first = False
                        else:
                            self._restarted.set()
                        await self._until_stop_or_restart()
            for s in servers:
                s.should_exit = True
            await asyncio.gather(*tasks)
        finally:
            await env.shutdown()

    async def _until_stop_or_restart(self) -> None:
        assert self._stop is not None and self._restart_requested is not None
        waiters = [
            asyncio.create_task(self._stop.wait()),
            asyncio.create_task(self._restart_requested.wait()),
        ]
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for w in waiters:
            w.cancel()
        self._restart_requested.clear()

    async def _wait_started(self, servers: list[uvicorn.Server]) -> None:
        for _ in range(STARTUP_POLLS):
            if all(s.started for s in servers):
                return
            await asyncio.sleep(STARTUP_POLL_SECONDS)
        raise RuntimeError("servers did not start")
