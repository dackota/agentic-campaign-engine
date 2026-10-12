"""One trace per campaign: a request for a campaign joins the trace `POST /campaigns` began.

The middleware sits outside the OpenTelemetry one. It finds the campaign a request is about
(the id in the path, or `campaignId` in a webhook's body), reads the campaign's stored
`traceparent` (`db.CampaignTrace`), and puts it on the request's headers before the
OpenTelemetry middleware makes the server span, so that span is a child of the campaign's
root and everything the request does lands in the trace.
"""

import json
import re
import uuid
from typing import Any

from ace_engine import db, telemetry
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CAMPAIGN_PATH = re.compile(r"^/campaigns/([0-9a-fA-F-]{36})(?:/|$)")
WEBHOOK_PREFIX = "/webhooks/"
MAX_PEEKED_BYTES = 64 * 1024  # the webhook routes' own cap
CAMPAIGN_FIELD = "campaignId"
MAX_CACHED_TRACES = 10_000
# A campaign's traceparent never changes once stored, so a read of it is kept: a page that
# polls a campaign would otherwise pay a database read on every request.
_cached: dict[uuid.UUID, str] = {}


def remember(campaign_id: uuid.UUID, traceparent: str) -> None:
    if len(_cached) >= MAX_CACHED_TRACES:
        _cached.pop(next(iter(_cached)))
    _cached[campaign_id] = traceparent


def _uuid_or_none(text: Any) -> uuid.UUID | None:
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


class CampaignTraceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        campaign_id: uuid.UUID | None = None
        replay: list[Message] = []
        match = CAMPAIGN_PATH.match(path)
        if match:
            campaign_id = _uuid_or_none(match.group(1))
        elif path.startswith(WEBHOOK_PREFIX):
            body, replay = await _peek_body(receive, scope)
            campaign_id = _campaign_in(body)
        traceparent = await self._traceparent(scope, campaign_id)
        if traceparent is not None:
            headers = [h for h in scope["headers"] if h[0] != telemetry.TRACEPARENT_HEADER.encode()]
            headers.append((telemetry.TRACEPARENT_HEADER.encode(), traceparent.encode()))
            scope = {**scope, "headers": headers}
        await self.app(scope, _replaying(replay, receive), send)

    async def _traceparent(self, scope: Scope, campaign_id: uuid.UUID | None) -> str | None:
        if campaign_id is None:
            return None
        if campaign_id in _cached:
            return _cached[campaign_id]
        engine = scope["app"].state.engine
        found = await run_in_threadpool(db.campaign_traceparent, engine, campaign_id)
        if found is not None:
            remember(campaign_id, found)
        return found


def _replaying(messages: list[Message], receive: Receive) -> Receive:
    """A receive that hands out the messages already read, then the live ones."""
    pending = list(messages)

    async def replay() -> Message:
        return pending.pop(0) if pending else await receive()

    return replay


def install_campaign_trace(app: FastAPI) -> None:
    """Wrap the whole middleware stack, so this runs outside the OpenTelemetry middleware,
    which `instrument_app` already put outermost: add_middleware would land inside it."""
    build = app.build_middleware_stack

    def build_outermost() -> ASGIApp:
        return CampaignTraceMiddleware(build())

    app.build_middleware_stack = build_outermost  # type: ignore[method-assign]
