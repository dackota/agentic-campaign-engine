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
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._postgres: PostgresContainer | None = None

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

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
            self._thread.join(timeout=60)
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

        assert self._postgres is not None
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        agent_port = free_port()
        env = await WorkflowEnvironment.start_time_skipping()
        try:
            settings = Settings(
                depth=self.depth,
                database_url=self._postgres.get_connection_url(),
                temporal_address=env.client.service_client.config.target_host,
                temporal_namespace=env.client.namespace,
                agent_url=f"http://127.0.0.1:{agent_port}",
            )
            servers = [
                uvicorn.Server(
                    uvicorn.Config(
                        self.agent.app, port=agent_port, host="127.0.0.1", log_level="warning"
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
            with ThreadPoolExecutor(max_workers=8) as executor:
                worker = build_worker(env.client, settings, executor)
                async with worker:
                    await self._wait_started(servers)
                    self._ready.set()
                    await self._stop.wait()
            for s in servers:
                s.should_exit = True
            await asyncio.gather(*tasks)
        finally:
            await env.shutdown()

    async def _wait_started(self, servers: list[uvicorn.Server]) -> None:
        for _ in range(600):
            if all(s.started for s in servers):
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("servers did not start")
