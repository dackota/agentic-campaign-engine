"""Alerts from Grafana: the in-app banner and the Slack notice.

Grafana's alert rules (manifests/observability/grafana/alerting.yaml) post to
`POST /alerts/webhook` with a shared bearer token. Each alert is kept once, by its
fingerprint. `GET /alerts` lists the ones firing, for the banner every signed-in user sees.
A firing alert posts one Slack notice when Slack is on, and so does its resolution; a repeat
of a firing alert posts nothing. The webhook is off while no token is set.
"""

import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from ace_engine import db
from ace_engine.settings import Settings
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from campaign_api.auth import Action, CurrentUser, authorize
from campaign_api.webhook_routes import _capped_body

log = logging.getLogger(__name__)

FIRING = "firing"
RESOLVED = "resolved"
MAX_ALERTS_PER_CALL = 100
MAX_TEXT_CHARS = 500
BEARER_PREFIX = "Bearer "


class AlertIn(BaseModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    fingerprint: str = Field(min_length=1, max_length=200)

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "")[:MAX_TEXT_CHARS]

    @property
    def summary(self) -> str:
        return self.annotations.get("summary", "")[:MAX_TEXT_CHARS]


class AlertsIn(BaseModel):
    alerts: list[AlertIn] = Field(max_length=MAX_ALERTS_PER_CALL)


class AlertOut(BaseModel):
    name: str
    summary: str
    fired_at: datetime


@dataclass(frozen=True)
class Notice:
    """A change worth a Slack message."""

    text: str


def _apply(session: Session, alert: AlertIn) -> Notice | None:
    """Record one alert; a Notice when it newly fired or newly resolved."""
    row = session.get(db.Alert, alert.fingerprint)
    if alert.status == FIRING:
        if row is None:
            session.add(
                db.Alert(
                    fingerprint=alert.fingerprint,
                    name=alert.name,
                    summary=alert.summary,
                    status=FIRING,
                )
            )
        elif row.status == FIRING:
            row.summary = alert.summary
            return None
        else:
            row.name, row.summary, row.status = alert.name, alert.summary, FIRING
            row.fired_at, row.resolved_at = datetime.now(UTC), None
        return Notice(f"ALERT firing: {alert.name}: {alert.summary}")
    if row is None or row.status != FIRING:
        return None
    row.status, row.resolved_at = RESOLVED, datetime.now(UTC)
    return Notice(f"ALERT resolved: {alert.name}")


def record(engine: Engine, alerts: list[AlertIn]) -> list[Notice]:
    with Session(engine) as session, session.begin():
        found = [_apply(session, a) for a in alerts]
    return [n for n in found if n is not None]


def firing(engine: Engine) -> list[AlertOut]:
    with Session(engine) as session:
        rows = session.query(db.Alert).filter_by(status=FIRING).order_by(db.Alert.fired_at).all()
        return [AlertOut(name=r.name, summary=r.summary, fired_at=r.fired_at) for r in rows]


async def post_to_slack(
    settings: Settings, text: str, client: httpx.AsyncClient | None = None
) -> None:
    """Best effort: a Slack outage must not fail the webhook, so it is logged (never the
    token) and dropped. A test passes its own `client`; otherwise one is opened here."""
    if not settings.slack_enabled:
        return
    try:
        if client is not None:
            await _post_notice(client, settings, text)
            return
        async with httpx.AsyncClient(timeout=settings.notify_timeout_seconds) as own:
            await _post_notice(own, settings, text)
    except httpx.HTTPError as exc:
        log.warning("slack alert notice failed: %s", type(exc).__name__)


async def _post_notice(client: httpx.AsyncClient, settings: Settings, text: str) -> None:
    response = await client.post(
        f"{settings.slack_url}/chat.postMessage",
        headers={"Authorization": f"Bearer {settings.slack_token}"},
        json={"channel": settings.slack_channel, "text": text},
    )
    response.raise_for_status()


def _check_token(request: Request, token: str) -> None:
    sent = request.headers.get("authorization", "")
    expected = f"{BEARER_PREFIX}{token}"
    if not hmac.compare_digest(sent.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="alert webhook needs its bearer token")


def register_alert_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/alerts")
    async def list_alerts(request: Request, user: CurrentUser) -> list[AlertOut]:
        authorize(user, Action.READ)
        return await run_in_threadpool(firing, request.app.state.engine)

    if not settings.alert_webhook_token.strip():
        return

    @app.post("/alerts/webhook", status_code=202)
    async def alert_webhook(request: Request) -> dict[str, int]:
        _check_token(request, settings.alert_webhook_token)
        body = await _capped_body(request)
        try:
            payload = AlertsIn.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"webhook body is not a Grafana alert: {exc.error_count()} errors",
            ) from None
        notices = await run_in_threadpool(record, request.app.state.engine, payload.alerts)
        for notice in notices:
            await post_to_slack(settings, notice.text)
        return {"received": len(payload.alerts)}
