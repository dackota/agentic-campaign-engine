"""The signed webhooks of the marketing systems (Marketo activity, Workfront task status):
each is verified, size-capped, and recorded once per event id."""

import uuid
from typing import Literal

from ace_engine import db, webhooks
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
