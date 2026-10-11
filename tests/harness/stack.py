"""Seam 1 harness: real Postgres, Dex with the demo users, Temporal's time-skipping test
server, the scripted A2A agent, the worker, and the Campaign API, started together on
free local ports.

One setting (`ACE_DEPTH`, read by `Depth.from_env`) picks fast or live depth. Live depth
is wired in a later ticket, so starting a live stack raises.
"""

import asyncio
import dataclasses
import secrets
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import TYPE_CHECKING, Any

import httpx
import uvicorn
from temporalio.testing import WorkflowEnvironment
from testcontainers.community.postgres import PostgresContainer

from tests.harness.dex import CLIENT_ID, Dex
from tests.harness.scripted_agent import ScriptedAgent

if TYPE_CHECKING:
    from ace_engine.settings import Settings

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
    def __init__(
        self,
        depth: str | None = None,
        api_port: int | None = None,
        dex_port: int | None = None,
        web_origin: str = "http://127.0.0.1:5173",
        integrations: bool = False,
    ) -> None:
        from ace_engine.settings import Depth

        self.depth = Depth.parse(depth) if depth is not None else Depth.from_env()
        self.agent = ScriptedAgent()
        self.api_port = api_port or free_port()
        self.marketo_port = free_port()
        self.dex = Dex(dex_port or free_port(), web_origin)
        # Slack and Google Docs are off unless asked for; on, each points at a local stand-in.
        self.integrations = integrations
        self.slack_port = free_port()
        self.google_port = free_port()
        self.slack_channel = "#ace-demo"
        self.slack_token = f"xoxb-{secrets.token_urlsafe(18)}"
        self.google_client_id = f"gid-{secrets.token_hex(4)}"
        self.google_client_secret = secrets.token_urlsafe(24)
        self.google_refresh_token = secrets.token_urlsafe(24)
        # Fresh per stack, never in code: the fake's OAuth2 client and its webhook key.
        self.marketo_client_id = f"ace-{secrets.token_hex(4)}"
        self.marketo_client_secret = secrets.token_urlsafe(24)
        self.marketo_webhook_secret = secrets.token_urlsafe(24)
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

    @property
    def slack_url(self) -> str:
        return f"http://127.0.0.1:{self.slack_port}"

    @property
    def google_url(self) -> str:
        return f"http://127.0.0.1:{self.google_port}"

    @property
    def slack_messages_url(self) -> str:
        """Every message the Slack stand-in received, as a JSON list."""
        return f"{self.slack_url}/_messages"

    @property
    def google_documents_url(self) -> str:
        """Every document the Google stand-in holds, as a JSON list."""
        return f"{self.google_url}/_documents"

    def marketo_malformed_reply(self, is_malformed: bool) -> None:
        """Make the fake Marketo answer sends with a reply that has no receipt id."""
        self.marketo_fault(malformed_reply=is_malformed)

    def marketo_drop_next_send_reply(self) -> None:
        """Make the fake Marketo record the next send, then answer it with a 503."""
        self.marketo_fault(drop_next_send_reply=True)

    def marketo_fault(
        self, *, malformed_reply: bool = False, drop_next_send_reply: bool = False
    ) -> None:
        response = httpx.put(
            f"{self.marketo_url}/_fault",
            json={
                "malformed_reply": malformed_reply,
                "drop_next_send_reply": drop_next_send_reply,
            },
            timeout=10,
        )
        assert response.status_code == 204, response.text

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
        self.dex.start()
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
        self.dex.stop()

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
                oidc_issuer=self.dex.issuer,
                oidc_client_id=CLIENT_ID,
                marketo_client_id=self.marketo_client_id,
                marketo_client_secret=self.marketo_client_secret,
                marketo_webhook_secret=self.marketo_webhook_secret,
            )
            if self.integrations:
                settings = dataclasses.replace(
                    settings,
                    slack_token=self.slack_token,
                    slack_channel=self.slack_channel,
                    slack_url=self.slack_url,
                    google_client_id=self.google_client_id,
                    google_client_secret=self.google_client_secret,
                    google_refresh_token=self.google_refresh_token,
                    google_token_url=f"{self.google_url}/token",
                    google_docs_url=self.google_url,
                )
            servers = self._servers(settings, agent_port)
            tasks = [asyncio.create_task(s.serve()) for s in servers]
            with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
                await self._wait_started(servers)
                await self._run_workers(env, settings, executor)
            for s in servers:
                s.should_exit = True
            await asyncio.gather(*tasks)
        finally:
            await env.shutdown()

    def _servers(self, settings: "Settings", agent_port: int) -> list[uvicorn.Server]:
        from campaign_api.main import create_app
        from fake_marketo.app import MarketoConfig
        from fake_marketo.app import create_app as create_marketo

        marketo = MarketoConfig(
            client_id=self.marketo_client_id,
            client_secret=self.marketo_client_secret,
            webhook_url=f"{self.api_url}/webhooks/marketo",
            webhook_secret=self.marketo_webhook_secret,
        )
        apps: list[tuple[Any, int]] = [
            (self.agent.app, agent_port),
            (create_marketo(marketo), self.marketo_port),
            (create_app(settings), self.api_port),
        ]
        if self.integrations:
            from fake_google.app import GoogleConfig
            from fake_google.app import create_app as create_google
            from fake_slack.app import SlackConfig
            from fake_slack.app import create_app as create_slack

            google = GoogleConfig(
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
                refresh_token=self.google_refresh_token,
            )
            apps += [
                (create_slack(SlackConfig(token=self.slack_token)), self.slack_port),
                (create_google(google), self.google_port),
            ]
        return [
            uvicorn.Server(uvicorn.Config(app, port=port, host="127.0.0.1", log_level="warning"))
            for app, port in apps
        ]

    async def _run_workers(
        self, env: WorkflowEnvironment, settings: "Settings", executor: ThreadPoolExecutor
    ) -> None:
        from campaign_worker.worker import build_worker

        assert self._stop is not None
        is_first = True
        while not self._stop.is_set():
            worker = build_worker(
                env.client, settings, executor, max_cached_workflows=NO_WORKFLOW_CACHE
            )
            async with worker:
                if is_first:
                    self._ready.set()
                    is_first = False
                else:
                    self._restarted.set()
                await self._until_stop_or_restart()

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
