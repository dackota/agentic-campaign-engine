"""One trace per campaign: a request for a campaign joins the trace `POST /campaigns` began.

The middleware sits outside the OpenTelemetry one. It finds the campaign a request is about
(the id in the path, or `campaignId` in a webhook's body), reads the campaign's stored
`traceparent` (`db.CampaignTrace`), and puts it on the request's headers before the
OpenTelemetry middleware makes the server span, so that span is a child of the campaign's
root and everything the request does lands in the trace.

Only a caller allowed to see the campaign joins its trace. A campaign path joins when the
request's token (the bearer header, or the `access_token` query) verifies and the user's
team can read the campaign's traceparent through row-level security. A webhook joins when
its body's signature verifies with its sender's secret. Anything else starts its own trace;
the middleware never answers a request itself, so the route decides the status.
"""

import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs

from ace_engine import db, row_security, telemetry, webhooks
from ace_engine.settings import Settings
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from campaign_api.auth import TokenVerifier
from campaign_api.webhook_routes import WORKFRONT_HEADERS

log = logging.getLogger(__name__)

CAMPAIGN_PATH = re.compile(r"^/campaigns/([0-9a-fA-F-]{36})(?:/|$)")
MARKETO_PATH = "/webhooks/marketo"
WORKFRONT_PATH = "/webhooks/workfront"
MAX_PEEKED_BYTES = 64 * 1024  # the webhook routes' own cap
CAMPAIGN_FIELD = "campaignId"
MAX_CACHED_TRACES = 10_000
BEARER_PREFIX = "bearer "
TOKEN_QUERY = "access_token"
# The cache key of a signed webhook's read: it reads as the system, not as a team.
SYSTEM: None = None
# A campaign's traceparent never changes once stored, so a read of it is kept: a page that
# polls a campaign would otherwise pay a database read on every request. The key names the
# team that read it, so one team's read is never served to another.
_cached: dict[tuple[uuid.UUID, str | None], str] = {}


@dataclass(frozen=True)
class WebhookSigner:
    """How one webhook sender signs: its secret and the names of its two headers."""

    secret: str
    names: webhooks.SignatureHeaders = webhooks.MARKETO_HEADERS

    def signed(self, headers: Mapping[str, str], body: bytes) -> bool:
        try:
            webhooks.verify(headers, body, self.secret, names=self.names)
        except webhooks.WebhookRejected:
            return False
        return True


def remember(campaign_id: uuid.UUID, team: str | None, traceparent: str) -> None:
    if len(_cached) >= MAX_CACHED_TRACES:
        _cached.pop(next(iter(_cached)))
    _cached[(campaign_id, team)] = traceparent


def _uuid_or_none(text: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(text))
    except ValueError:
        return None


async def _peek_body(receive: Receive, scope: Scope) -> tuple[bytes, list[Message]]:
    """The body of a small request and the messages read, to replay to the route. A body
    that is declared or turns out larger than the cap is left to the route to reject."""
    declared = dict(scope["headers"]).get(b"content-length", b"")
    if not declared.isdigit() or int(declared) > MAX_PEEKED_BYTES:
        return b"", []
    messages: list[Message] = []
    body = b""
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            return b"", messages
        body += message.get("body", b"")
        if len(body) > MAX_PEEKED_BYTES:
            return b"", messages
        if not message.get("more_body", False):
            return body, messages


def _campaign_in(body: bytes) -> uuid.UUID | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    return _uuid_or_none(parsed.get(CAMPAIGN_FIELD)) if isinstance(parsed, dict) else None


def _token(scope: Scope) -> str | None:
    """The token a route would read: the bearer header first, then the `access_token` query."""
    authorization = Headers(scope=scope).get("authorization", "")
    if authorization.lower().startswith(BEARER_PREFIX):
        return authorization[len(BEARER_PREFIX) :].strip() or None
    tokens = parse_qs(scope.get("query_string", b"").decode("latin-1")).get(TOKEN_QUERY)
    return tokens[0] if tokens else None


class CampaignTraceMiddleware:
    def __init__(self, app: ASGIApp, signers: Mapping[str, WebhookSigner]) -> None:
        self.app = app
        self.signers = signers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        traceparent: str | None = None
        replay: list[Message] = []
        match = CAMPAIGN_PATH.match(path)
        if match:
            traceparent = await self._for_user(scope, _uuid_or_none(match.group(1)))
        elif path in self.signers:
            body, replay = await _peek_body(receive, scope)
            if self.signers[path].signed(Headers(scope=scope), body):
                traceparent = await self._read(scope, _campaign_in(body), SYSTEM)
        if traceparent is not None:
            headers = [h for h in scope["headers"] if h[0] != telemetry.TRACEPARENT_HEADER.encode()]
            headers.append((telemetry.TRACEPARENT_HEADER.encode(), traceparent.encode()))
            scope = {**scope, "headers": headers}
        await self.app(scope, _replaying(replay, receive), send)

    async def _for_user(self, scope: Scope, campaign_id: uuid.UUID | None) -> str | None:
        """The traceparent as the request's user's team sees it; None for no valid token or
        no team. A failed check is the route's to answer, so nothing is raised here."""
        token = _token(scope)
        if campaign_id is None or token is None:
            return None
        verifier: TokenVerifier = scope["app"].state.verifier
        try:
            user = await run_in_threadpool(verifier.verify, token)
        except Exception:  # noqa: BLE001 - any failure means no trace join; the route answers
            return None
        if user.team is None:
            return None
        return await self._read(scope, campaign_id, user.team)

    async def _read(
        self, scope: Scope, campaign_id: uuid.UUID | None, team: str | None
    ) -> str | None:
        """The campaign's traceparent, read as `team` (as the system for SYSTEM)."""
        if campaign_id is None:
            return None
        if (campaign_id, team) in _cached:
            return _cached[(campaign_id, team)]
        engine = scope["app"].state.engine
        if team is not SYSTEM:
            engine = row_security.for_team(engine, team)
        try:
            found = await run_in_threadpool(db.campaign_traceparent, engine, campaign_id)
        except Exception:  # noqa: BLE001 - a failed read starts a trace of its own
            log.exception("cannot read the trace of campaign %s", campaign_id)
            return None
        if found is not None:
            remember(campaign_id, team, found)
        return found


def _replaying(messages: list[Message], receive: Receive) -> Receive:
    """A receive that hands out the messages already read, then the live ones."""
    pending = list(messages)

    async def replay() -> Message:
        return pending.pop(0) if pending else await receive()

    return replay


def _webhook_signers(settings: Settings) -> dict[str, WebhookSigner]:
    """How each registered webhook is signed, by its path."""
    signers = {MARKETO_PATH: WebhookSigner(settings.marketo_webhook_secret)}
    if settings.has_workfront:
        signers[WORKFRONT_PATH] = WebhookSigner(
            settings.workfront_webhook_secret, WORKFRONT_HEADERS
        )
    return signers


def install_campaign_trace(app: FastAPI, settings: Settings) -> None:
    """Wrap the whole middleware stack, so this runs outside the OpenTelemetry middleware,
    which `instrument_app` already put outermost: add_middleware would land inside it."""
    build = app.build_middleware_stack
    signers = _webhook_signers(settings)

    def build_outermost() -> ASGIApp:
        return CampaignTraceMiddleware(build(), signers)

    app.build_middleware_stack = build_outermost  # type: ignore[method-assign]
