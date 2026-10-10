"""The Marketo activity webhook: verified, size-capped, and recorded once per event id."""

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
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_EVENT_ID_CHARS = 200


class ActivityEvent(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(min_length=1, max_length=MAX_EVENT_ID_CHARS)
    type: Literal["send", "open", "click", "bounce", "unsubscribe"]
    campaignId: uuid.UUID = Field(strict=False)  # noqa: N815 (Marketo's name)
    variant: Literal["A", "B"]


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


def _record(engine: Engine, event: ActivityEvent) -> None:
    """Store the event once; 422 for an unknown campaign, 409 for a replayed id."""
    with Session(engine) as session:
        if session.get(db.Campaign, event.campaignId) is None:
            raise HTTPException(status_code=422, detail="webhook names an unknown campaign")
        session.add(
            db.Activity(
                source=MARKETO_SOURCE,
                event_id=event.id,
                campaign_id=event.campaignId,
                type=event.type,
                variant=event.variant,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="webhook id was already received") from None


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
