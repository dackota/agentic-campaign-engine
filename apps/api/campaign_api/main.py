"""The Campaign API: create a campaign from a threat report, read it back with its draft."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from ace_engine import db
from ace_engine.settings import TASK_QUEUE, WORKFLOW_NAME, Settings
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, StringConstraints
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

MAX_REPORT_CHARS = 100_000
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

    @classmethod
    def of(cls, c: db.Campaign) -> "CampaignOut":
        return cls(
            id=c.id,
            report=c.report,
            status=c.status,
            draft=c.draft,
            failure_reason=c.failure_reason,
        )


def _insert(engine: Engine, campaign_id: uuid.UUID, report: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(db.Campaign(id=campaign_id, report=report))


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
        )

    @app.get("/campaigns/{campaign_id}")
    def get_campaign(campaign_id: uuid.UUID, request: Request) -> CampaignOut:
        with Session(request.app.state.engine) as session:
            campaign = session.get(db.Campaign, campaign_id)
            if campaign is None:
                raise HTTPException(status_code=404, detail="campaign not found")
            return CampaignOut.of(campaign)

    return app
