"""Seam 1 harness: real Postgres, Dex with the demo users, Temporal's time-skipping test
server, the scripted A2A agent, the fake Marketo, the fake Workfront, the worker, and the
Campaign API, started together on free local ports.

One setting (`ACE_DEPTH`, read by `Depth.from_env`) picks fast or live depth. At live
depth the same stack runs on this machine, but the worker calls the real kagent Agents on
the `k3d-ace` cluster through a `kubectl port-forward` to the kagent controller, so the
model calls go through agentgateway. The cluster must be up (`make up`).
"""

import asyncio
import dataclasses
import secrets
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import TYPE_CHECKING, Any

import httpx
import uvicorn
from ace_engine.settings import Depth
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.testing import WorkflowEnvironment
from testcontainers.community.postgres import PostgresContainer

from tests.harness.dex import CLIENT_ID, Dex
from tests.harness.scripted_agent import ScriptedAgent

if TYPE_CHECKING:
    from ace_engine.settings import Settings
    from fastapi import FastAPI

POSTGRES_IMAGE = "postgres:16-alpine"
START_TIMEOUT_SECONDS = 180
STOP_TIMEOUT_SECONDS = 60
WORKER_THREADS = 8
# Temporal's test server never falls back from a stopped worker's sticky queue, so a
# restarted worker would wait forever. No cache means every task replays from history.
NO_WORKFLOW_CACHE = 0
STARTUP_POLLS = 600
STARTUP_POLL_SECONDS = 0.1
KAGENT_CONTEXT = "k3d-ace"
KAGENT_NAMESPACE = "kagent"
KAGENT_CONTROLLER_PORT = 8083
# The controller serves each Agent under /agents/<namespace>/<agent>.
KAGENT_AGENTS_PATH = f"/agents/{KAGENT_NAMESPACE}"
KAGENT_READY_AGENT = "ace-email-writer"
KAGENT_READY_SECONDS = 60
KAGENT_PROBE_TIMEOUT_SECONDS = 5
KAGENT_PROBE_INTERVAL_SECONDS = 1
# A real model takes seconds per reply, where the scripted agent takes none.
LIVE_AGENT_TIMEOUT_SECONDS = 180.0


def kagent_port_forward_command(local_port: int) -> list[str]:
    """The command that opens the kagent controller on a local port. It names the `ace`
    cluster's context, never the active one."""
    return [
        "kubectl",
        "--context",
        KAGENT_CONTEXT,
        "port-forward",
        "-n",
        KAGENT_NAMESPACE,
        "svc/kagent-controller",
        f"{local_port}:{KAGENT_CONTROLLER_PORT}",
    ]


_SPAN_EXPORTER = InMemorySpanExporter()


def _install_span_exporter() -> InMemorySpanExporter:
    """The test exporter, set as the process's tracer provider the first time a stack is built
    (OpenTelemetry allows one provider per process)."""
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
        trace.set_tracer_provider(provider)
    return _SPAN_EXPORTER


_METRIC_READER = InMemoryMetricReader()


def _install_metric_reader() -> InMemoryMetricReader:
    """The test metric reader, set up the first time a stack is built (one meter provider per
    process, like the tracer provider)."""
    if not isinstance(metrics.get_meter_provider(), MeterProvider):
        metrics.set_meter_provider(MeterProvider(metric_readers=[_METRIC_READER]))
    return _METRIC_READER


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclasses.dataclass(frozen=True)
class Pinned:
    """What a browser spec has to know before the stack starts. None is chosen fresh."""

    api_port: int | None = None
    dex_port: int | None = None
    web_origin: str = "http://127.0.0.1:5173"
    marketo_port: int | None = None
    alert_webhook_token: str | None = None


NOTHING_PINNED = Pinned()


class Stack:
    def __init__(
        self,
        depth: str | None = None,
        integrations: bool = False,
        pinned: Pinned = NOTHING_PINNED,
    ) -> None:
        self.depth = Depth.parse(depth) if depth is not None else Depth.from_env()
        # Every service runs in this process, so one in-memory exporter holds every span.
        self.spans = _install_span_exporter()
        self._metric_reader = _install_metric_reader()
        # What Grafana's alert webhook sends as its bearer token. Fresh per stack unless a
        # browser spec has to know it up front.
        self.alert_webhook_token = pinned.alert_webhook_token or secrets.token_urlsafe(24)
        self.agent = ScriptedAgent()
        self.api_port = pinned.api_port or free_port()
        self.marketo_port = pinned.marketo_port or free_port()
        self.cms_port = free_port()
        self.s3_port = free_port()
        self.s3_bucket = "ace-assets"
        self.workfront_port = free_port()
        self.dex = Dex(pinned.dex_port or free_port(), pinned.web_origin)
        # Slack and Google Docs are off unless asked for; on, each points at a local stand-in.
        self.integrations = integrations
        self.slack_port = free_port()
        self.google_port = free_port()
        self.slack_channel = "#ace-demo"
        self.slack_token = f"xoxb-{secrets.token_urlsafe(18)}"
        self.google_client_id = f"gid-{secrets.token_hex(4)}"
        self.google_client_secret = secrets.token_urlsafe(24)
        self.google_refresh_token = secrets.token_urlsafe(24)
        self._fresh_secrets()
        self._restart_requested: asyncio.Event | None = None
        self._restarted = threading.Event()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._postgres: PostgresContainer | None = None
        self._port_forward: subprocess.Popen[bytes] | None = None
        self._kagent_url = ""

    def _fresh_secrets(self) -> None:
        # Fresh per stack, never in code: the fake's OAuth2 client and its webhook key.
        self.marketo_client_id = f"ace-{secrets.token_hex(4)}"
        self.marketo_client_secret = secrets.token_urlsafe(24)
        self.marketo_webhook_secret = secrets.token_urlsafe(24)
        self.workfront_client_id = f"ace-{secrets.token_hex(4)}"
        self.workfront_client_secret = secrets.token_urlsafe(24)
        self.workfront_webhook_secret = secrets.token_urlsafe(24)

    def _metric_points(self, name: str, **attributes: str) -> list[Any]:
        data = self._metric_reader.get_metrics_data()
        found = []
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name != name:
                        continue
                    found += [
                        p
                        for p in metric.data.data_points
                        if all((p.attributes or {}).get(k) == v for k, v in attributes.items())
                    ]
        return found

    def metric_total(self, name: str, **attributes: str) -> float:
        """The sum of a counter, or of a histogram's recorded values, over the data points
        whose attributes include `attributes`."""
        points = self._metric_points(name, **attributes)
        totals: list[float] = [
            float(getattr(p, "value", None) or getattr(p, "sum", None) or 0) for p in points
        ]
        return sum(totals)

    def metric_count(self, name: str, **attributes: str) -> int:
        """How many values a histogram recorded."""
        return int(sum(p.count for p in self._metric_points(name, **attributes)))

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

    @property
    def cms_url(self) -> str:
        return f"http://127.0.0.1:{self.cms_port}"

    @property
    def s3_url(self) -> str:
        return f"http://127.0.0.1:{self.s3_port}"

    def drop_next_content_replies(self) -> None:
        """Make the fake CMS and the fake S3 store keep the next write, then answer 503."""
        for url in (self.cms_url, self.s3_url):
            response = httpx.put(f"{url}/_fault", json={"drop_next_reply": True}, timeout=10)
            assert response.status_code == 204, response.text

    @property
    def workfront_url(self) -> str:
        return f"http://127.0.0.1:{self.workfront_port}"

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

    def marketo_audience(self, *, seed: int, time_speed: float) -> None:
        """Set the simulated audience's seed and its time speed (simulated seconds per
        real second) for the sends that follow."""
        response = httpx.put(
            f"{self.marketo_url}/_audience",
            json={"seed": seed, "time_speed": time_speed},
            timeout=10,
        )
        assert response.status_code == 204, response.text

    def marketo_planned_events(self, campaign_id: str) -> list[dict[str, Any]]:
        """Every open and click the fake planned for this campaign, in simulated order."""
        response = httpx.get(
            f"{self.marketo_url}/_audience/events", params={"externalId": campaign_id}, timeout=10
        )
        assert response.status_code == 200, response.text
        events: list[dict[str, Any]] = response.json()
        return events

    def restart_worker(self) -> None:
        """Stop the worker and start a fresh one; the workflow resumes by replay."""
        assert self._loop is not None and self._restart_requested is not None
        self._restarted.clear()
        self._loop.call_soon_threadsafe(self._restart_requested.set)
        if not self._restarted.wait(START_TIMEOUT_SECONDS):
            raise RuntimeError("worker did not restart")

    def start(self) -> "Stack":
        if self.depth is Depth.LIVE:
            self._open_kagent()
        self._postgres = PostgresContainer(POSTGRES_IMAGE, driver="psycopg")
        self._postgres.start()
        self.dex.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_SECONDS) or self._error is not None:
            self.stop()
            raise RuntimeError(f"stack did not start: {self._error!r}")
        return self

    def _open_kagent(self) -> None:
        """Forward the kagent controller to a local port and wait until the email writer
        Agent answers for its card."""
        port = free_port()
        self._port_forward = subprocess.Popen(
            kagent_port_forward_command(port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._kagent_url = f"http://127.0.0.1:{port}{KAGENT_AGENTS_PATH}"
        card = f"{self._kagent_url}/{KAGENT_READY_AGENT}/.well-known/agent-card.json"
        deadline = time.monotonic() + KAGENT_READY_SECONDS
        while time.monotonic() < deadline:
            try:
                if httpx.get(card, timeout=KAGENT_PROBE_TIMEOUT_SECONDS).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(KAGENT_PROBE_INTERVAL_SECONDS)
        self._close_kagent()
        raise RuntimeError(f"kagent Agent {KAGENT_READY_AGENT} not reachable on {KAGENT_CONTEXT}")

    def _close_kagent(self) -> None:
        if self._port_forward is not None:
            self._port_forward.terminate()
            self._port_forward.wait(timeout=STOP_TIMEOUT_SECONDS)
            self._port_forward = None

    def stop(self) -> None:
        self._close_kagent()
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

        assert self._postgres is not None
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._restart_requested = asyncio.Event()
        agent_port = free_port()
        from ace_engine import telemetry

        env = await WorkflowEnvironment.start_time_skipping(
            interceptors=telemetry.temporal_interceptors()
        )
        try:
            settings = self._settings(env, agent_port)
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

    def _settings(self, env: WorkflowEnvironment, agent_port: int) -> "Settings":
        from ace_engine.settings import Settings

        assert self._postgres is not None
        is_live = self.depth is Depth.LIVE
        settings = Settings(
            depth=self.depth,
            database_url=self._postgres.get_connection_url(),
            temporal_address=env.client.service_client.config.target_host,
            temporal_namespace=env.client.namespace,
            agent_url=self._kagent_url if is_live else f"http://127.0.0.1:{agent_port}",
            agent_timeout_seconds=(
                LIVE_AGENT_TIMEOUT_SECONDS if is_live else Settings.agent_timeout_seconds
            ),
            marketo_url=self.marketo_url,
            cms_url=self.cms_url,
            s3_url=self.s3_url,
            s3_bucket=self.s3_bucket,
            oidc_issuer=self.dex.issuer,
            oidc_client_id=CLIENT_ID,
            marketo_client_id=self.marketo_client_id,
            marketo_client_secret=self.marketo_client_secret,
            marketo_webhook_secret=self.marketo_webhook_secret,
            workfront_url=self.workfront_url,
            workfront_client_id=self.workfront_client_id,
            workfront_client_secret=self.workfront_client_secret,
            workfront_webhook_secret=self.workfront_webhook_secret,
            alert_webhook_token=self.alert_webhook_token,
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
        return settings

    def _servers(self, settings: "Settings", agent_port: int) -> list[uvicorn.Server]:
        from campaign_api.main import create_app
        from fake_cms.app import create_app as create_cms
        from fake_marketo.app import MarketoConfig
        from fake_marketo.app import create_app as create_marketo
        from fake_s3.app import create_app as create_s3
        from fake_workfront.app import WorkfrontConfig
        from fake_workfront.app import create_app as create_workfront

        marketo = MarketoConfig(
            client_id=self.marketo_client_id,
            client_secret=self.marketo_client_secret,
            webhook_url=f"{self.api_url}/webhooks/marketo",
            webhook_secret=self.marketo_webhook_secret,
        )
        workfront = WorkfrontConfig(
            client_id=self.workfront_client_id,
            client_secret=self.workfront_client_secret,
            webhook_url=f"{self.api_url}/webhooks/workfront",
            webhook_secret=self.workfront_webhook_secret,
        )
        apps: list[tuple[FastAPI, int]] = [
            (self.agent.app, agent_port),
            (create_marketo(marketo), self.marketo_port),
            (create_cms(), self.cms_port),
            (create_s3(), self.s3_port),
            (create_workfront(workfront), self.workfront_port),
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
