"""The Campaign API: create a campaign from a threat report, read it back with its draft."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from ace_engine import db
from ace_engine.settings import APPROVE_SIGNAL, TASK_QUEUE, WORKFLOW_NAME, Settings
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

MAX_REPORT_CHARS = 100_000
EVENT_POLL_SECONDS = 0.1
FINAL_STATES = {db.AWAITING_APPROVAL, db.FAILED}
Report = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=MAX_REPORT_CHARS)
]


class NewCampaign(BaseModel):
    report: Report

    def model_post_init(self, _context: Any) -> None:
        if not self.report.strip():
            raise ValueError("report must not be blank")


class CampaignOut(BaseModel):
    id: uuid.UUID
    report: str
    status: str
    draft: dict[str, Any] | None
    failure_reason: str | None
    receipt: str | None

    @classmethod
    def of(cls, c: db.Campaign) -> "CampaignOut":
        return cls(
            id=c.id,
            report=c.report,
            status=c.status,
            draft=c.draft,
            failure_reason=c.failure_reason,
            receipt=c.receipt,
        )


def _insert(engine: Engine, campaign_id: uuid.UUID, report: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(db.Campaign(id=campaign_id, report=report))


def _set_status(engine: Engine, campaign_id: uuid.UUID, wanted: str, new: str) -> bool:
    """Move the campaign `wanted` -> `new` in one statement; False if it was not in `wanted`."""
    with Session(engine) as session, session.begin():
        result = session.execute(
            update(db.Campaign)
            .where(db.Campaign.id == campaign_id, db.Campaign.status == wanted)
            .values(status=new)
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]


def _find(engine: Engine, campaign_id: uuid.UUID) -> CampaignOut | None:
    with Session(engine) as session:
        campaign = session.get(db.Campaign, campaign_id)
        return None if campaign is None else CampaignOut.of(campaign)


async def _found(engine: Engine, campaign_id: uuid.UUID) -> CampaignOut:
    """The campaign, or a 404 when there is none. Every route's missing-campaign check."""
    campaign = await run_in_threadpool(_find, engine, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


def _register_approval_route(app: FastAPI) -> None:
    @app.post("/campaigns/{campaign_id}/approve", status_code=202)
    async def approve_campaign(campaign_id: uuid.UUID, request: Request) -> CampaignOut:
        engine = request.app.state.engine
        is_claimed = await run_in_threadpool(
            _set_status, engine, campaign_id, db.AWAITING_APPROVAL, db.SENDING
        )
        if not is_claimed:
            await _found(engine, campaign_id)
            raise HTTPException(status_code=409, detail="campaign is not waiting for approval")
        try:
            handle = request.app.state.temporal.get_workflow_handle(f"campaign-{campaign_id}")
            await handle.signal(APPROVE_SIGNAL)
        except Exception:
            await run_in_threadpool(
                _set_status, engine, campaign_id, db.SENDING, db.AWAITING_APPROVAL
            )
            raise
        return await _found(engine, campaign_id)


def _sse(event: db.RunEvent) -> str:
    data = {
        "seq": event.seq,
        "step": event.step,
        "status": event.status,
        "reason": event.reason,
    }
    return f"id: {event.seq}\nevent: step\ndata: {json.dumps(data)}\n\n"


async def _event_stream(
    engine: Engine, campaign_id: uuid.UUID, after_seq: int
) -> AsyncIterator[str]:
    """Replay what happened after `after_seq`, then follow until the run's final state."""
    while True:
        events = await run_in_threadpool(db.events_after, engine, campaign_id, after_seq)
        for event in events:
            after_seq = event.seq
            yield _sse(event)
            if event.step == db.RUN_STEP and event.status in FINAL_STATES:
                return
        await asyncio.sleep(EVENT_POLL_SECONDS)


def _add_event_routes(app: FastAPI) -> None:
    @app.get("/campaigns/{campaign_id}/events")
    async def campaign_events(
        campaign_id: uuid.UUID,
        request: Request,
        last_event_id: Annotated[int, Header(ge=0)] = 0,
    ) -> StreamingResponse:
        await _found(request.app.state.engine, campaign_id)
        return StreamingResponse(
            _event_stream(request.app.state.engine, campaign_id, last_event_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = db.make_engine(settings.database_url)
        app.state.temporal = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        yield
        app.state.engine.dispose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/campaigns", status_code=201)
    async def create_campaign(body: NewCampaign, request: Request) -> CampaignOut:
        campaign_id = uuid.uuid4()
        await run_in_threadpool(_insert, request.app.state.engine, campaign_id, body.report)
        await request.app.state.temporal.start_workflow(
            WORKFLOW_NAME,
            args=[str(campaign_id), body.report],
            id=f"campaign-{campaign_id}",
            task_queue=TASK_QUEUE,
        )
        return CampaignOut(
            id=campaign_id,
            report=body.report,
            status=db.DRAFTING,
            draft=None,
            failure_reason=None,
            receipt=None,
        )

    @app.get("/campaigns/{campaign_id}")
    async def get_campaign(campaign_id: uuid.UUID, request: Request) -> CampaignOut:
        return await _found(request.app.state.engine, campaign_id)

    _register_approval_route(app)
    _add_event_routes(app)

    return app
