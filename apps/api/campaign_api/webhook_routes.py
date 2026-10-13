"""The signed webhooks of the marketing systems (Marketo activity, Workfront task status):
each is verified, size-capped, and recorded once per event id."""

import logging
import uuid
from typing import Literal, NamedTuple

import httpx
from ace_engine import db, learnings, webhooks
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from campaign_api.ab_result import decide

log = logging.getLogger(__name__)
MARKETO_SOURCE = "marketo"
WORKFRONT_SOURCE = "workfront"
WORKFRONT_HEADERS = webhooks.SignatureHeaders("X-Workfront-Signature", "X-Workfront-Timestamp")
MAX_STATUS_CHARS = 40
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_EVENT_ID_CHARS = 200


class ActivityEvent(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(min_length=1, max_length=MAX_EVENT_ID_CHARS)
    type: Literal["send", "open", "click", "bounce", "unsubscribe"]
    campaignId: uuid.UUID = Field(strict=False)  # noqa: N815 (Marketo's name)
    variant: Literal["A", "B"]


class TaskStatusChange(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(min_length=1, max_length=MAX_EVENT_ID_CHARS)
    taskID: str = Field(min_length=1, max_length=MAX_EVENT_ID_CHARS)  # noqa: N815
    campaignId: uuid.UUID = Field(strict=False)  # noqa: N815 (the fake's name)
    status: str = Field(min_length=1, max_length=MAX_STATUS_CHARS)


class ActivityOut(BaseModel):
    id: str
    type: str
    variant: str


async def _capped_body(request: Request) -> bytes:
    """The request body, or a 413 as soon as it passes MAX_WEBHOOK_BYTES."""
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="webhook body is too large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="webhook body is too large")
    return bytes(body)


def _record_once(engine: Engine, campaign_id: uuid.UUID, row: db.Base) -> None:
    """Store the event row once; 422 for an unknown campaign, 409 for a replayed id."""
    with Session(engine) as session:
        if session.get(db.Campaign, campaign_id) is None:
            raise HTTPException(status_code=422, detail="webhook names an unknown campaign")
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="webhook id was already received") from None


def _record(engine: Engine, event: ActivityEvent) -> None:
    row = db.Activity(
        source=MARKETO_SOURCE,
        event_id=event.id,
        campaign_id=event.campaignId,
        type=event.type,
        variant=event.variant,
    )
    _record_once(engine, event.campaignId, row)


def _learn_if_called(engine: Engine, campaign_id: uuid.UUID, embed: learnings.Embed) -> None:
    """When the A/B test can now call a winner, keep its winning lines as a learning. The
    activity is already recorded: a failure here (the gateway's embedding call) is logged,
    and the campaign's next open tries again."""
    with Session(engine) as session:
        engagement = engagement_by_variant(session, campaign_id)
    result = decide(engagement)
    if result.winner is None or result.confidence is None:
        return
    winner = learnings.Winner(result.winner, result.confidence, engagement)
    try:
        learnings.learn_from_winner(engine, campaign_id, winner, embed)
    except (httpx.HTTPError, ValueError, SQLAlchemyError):
        log.exception("could not keep the A/B winner of campaign %s as a learning", campaign_id)


def _record_task_status(engine: Engine, event: TaskStatusChange) -> None:
    row = db.TaskStatusEvent(
        source=WORKFRONT_SOURCE,
        event_id=event.id,
        campaign_id=event.campaignId,
        task_id=event.taskID,
        status=event.status,
    )
    _record_once(engine, event.campaignId, row)


def activities(engine: Engine, campaign_id: uuid.UUID) -> list[ActivityOut]:
    with Session(engine) as session:
        rows = (
            session.query(db.Activity).filter_by(campaign_id=campaign_id).order_by(db.Activity.seq)
        )
        return [ActivityOut(id=r.event_id, type=r.type, variant=r.variant) for r in rows]


class Engagement(NamedTuple):
    opens: int
    clicks: int


NO_ENGAGEMENT = Engagement(opens=0, clicks=0)


def engagement_by_campaign(session: Session) -> dict[uuid.UUID, Engagement]:
    """Opens and clicks of every visible campaign that has any, both variants together."""
    rows = session.execute(
        select(db.Activity.campaign_id, db.Activity.type, func.count())
        .where(db.Activity.type.in_(("open", "click")))
        .group_by(db.Activity.campaign_id, db.Activity.type)
    )
    found: dict[uuid.UUID, Engagement] = {}
    for campaign_id, kind, total in rows:
        field = "opens" if kind == "open" else "clicks"
        found[campaign_id] = found.get(campaign_id, NO_ENGAGEMENT)._replace(**{field: total})
    return found


def engagement_by_variant(session: Session, campaign_id: uuid.UUID) -> dict[str, dict[str, int]]:
    """Opens and clicks per variant label: {"A": {"opens": 3, "clicks": 1}, ...}."""
    rows = session.execute(
        select(db.Activity.variant, db.Activity.type, func.count())
        .where(db.Activity.campaign_id == campaign_id, db.Activity.type.in_(("open", "click")))
        .group_by(db.Activity.variant, db.Activity.type)
    )
    shown: dict[str, dict[str, int]] = {}
    for variant, kind, total in rows:
        per_variant = shown.setdefault(variant, {"opens": 0, "clicks": 0})
        per_variant["opens" if kind == "open" else "clicks"] = total
    return shown


def register_webhook_routes(app: FastAPI, secret: str) -> None:
    @app.post("/webhooks/marketo", status_code=202)
    async def marketo_webhook(request: Request) -> dict[str, str]:
        body = await _capped_body(request)
        try:
            webhooks.verify(request.headers, body, secret)
        except webhooks.WebhookRejected as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from None
        try:
            event = ActivityEvent.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"webhook body is not an activity: {exc.error_count()} errors",
            ) from None
        await run_in_threadpool(_record, request.app.state.engine, event)
        if event.type == "open":
            await run_in_threadpool(
                _learn_if_called,
                request.app.state.engine,
                event.campaignId,
                request.app.state.embed,
            )
        return {"id": event.id}


def register_workfront_routes(app: FastAPI, secret: str) -> None:
    @app.post("/webhooks/workfront", status_code=202)
    async def workfront_webhook(request: Request) -> dict[str, str]:
        body = await _capped_body(request)
        try:
            webhooks.verify(request.headers, body, secret, names=WORKFRONT_HEADERS)
        except webhooks.WebhookRejected as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from None
        try:
            event = TaskStatusChange.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"webhook body is not a task status: {exc.error_count()} errors",
            ) from None
        await run_in_threadpool(_record_task_status, request.app.state.engine, event)
        return {"id": event.id}
