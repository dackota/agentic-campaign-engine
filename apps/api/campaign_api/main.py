"""The Campaign API: create a campaign from a threat report on a saved workflow, read it
back with its draft and the steps of the workflow it pinned.

Every route but /healthz and the signed webhooks needs a signed-in user; `auth` holds the
role rules."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from ace_engine import dag as graph
from ace_engine import db
from ace_engine.settings import (
    APPROVE_SIGNAL,
    RETRY_SIGNAL,
    TASK_QUEUE,
    WORKFLOW_NAME,
    Settings,
)
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from render_service.email import EmailTooLarge, render_email
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

from campaign_api.auth import Action, BrowserUser, CurrentUser, TokenVerifier, authorize
from campaign_api.webhook_routes import ActivityOut, activities, register_webhook_routes
from campaign_api.workflows import NAME_PATTERN, latest_version, register_workflow_routes

MAX_REPORT_CHARS = 100_000
EVENT_POLL_SECONDS = 0.1
FINAL_STATES = {db.AWAITING_APPROVAL, db.FAILED, db.SENT, db.FINISHED}
Report = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=MAX_REPORT_CHARS)
]


class NewCampaign(BaseModel):
    report: Report
    # The saved workflow to run, at its latest version; None runs the default workflow.
    workflow: str | None = Field(default=None, pattern=NAME_PATTERN)

    def model_post_init(self, _context: Any) -> None:
        if not self.report.strip():
            raise ValueError("report must not be blank")


class CampaignOut(BaseModel):
    id: uuid.UUID
    report: str
    team: str
    created_by: str
    status: str
    draft: dict[str, Any] | None
    variant_b: dict[str, Any] | None
    failure_reason: str | None
    receipt: str | None
    workflow: str | None
    workflow_version: int | None
    steps: list[dict[str, Any]]

    @classmethod
    def of(cls, c: db.Campaign) -> "CampaignOut":
        return cls(
            id=c.id,
            report=c.report,
            team=c.team,
            created_by=c.created_by,
            status=c.status,
            draft=c.draft,
            variant_b=c.variant_b,
            failure_reason=c.failure_reason,
            receipt=c.receipt,
            workflow=c.workflow_name,
            workflow_version=c.workflow_version,
            steps=[
                {**s, "idempotency_key": graph.step_key(str(c.id), s["id"])}
                for s in graph.ordered(c.dag)
            ],
        )


class Me(BaseModel):
    subject: str
    email: str
    team: str | None
    roles: list[str]


def _insert(engine: Engine, campaign: db.Campaign) -> CampaignOut:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(campaign)
        session.flush()
        return CampaignOut.of(campaign)


def _list(engine: Engine) -> list[CampaignOut]:
    return [CampaignOut.of(c) for c in db.list_campaigns(engine)]


async def _pinned(engine: Engine, workflow: str | None) -> tuple[str | None, int | None, Any]:
    """The workflow name, version, and DAG a new run pins: the latest saved version."""
    if workflow is None:
        return None, None, graph.default_dag()
    found = await latest_version(engine, workflow)
    if found is None:
        raise HTTPException(status_code=422, detail=f"workflow {workflow!r} has no saved version")
    return found.name, found.version, found.dag


def _set_status(engine: Engine, campaign_id: uuid.UUID, wanted: str, new: str) -> bool:
    """Move the campaign `wanted` -> `new` in one statement; False if it was not in `wanted`."""
    with Session(engine) as session, session.begin():
        result = session.execute(
            update(db.Campaign)
            .where(db.Campaign.id == campaign_id, db.Campaign.status == wanted)
            .values(status=new)
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]


def _claim_retry(engine: Engine, campaign_id: uuid.UUID) -> bool:
    """Move a failed campaign to retrying and clear its reason; False if it had not failed."""
    with Session(engine) as session, session.begin():
        result = session.execute(
            update(db.Campaign)
            .where(db.Campaign.id == campaign_id, db.Campaign.status == db.FAILED)
            .values(status=db.RETRYING, failure_reason=None)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            return False
        db.add_event(session, campaign_id, db.RUN_STEP, db.RETRYING)
        return True


def _undo_retry(engine: Engine, campaign_id: uuid.UUID, reason: str | None) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(db.Campaign)
            .where(db.Campaign.id == campaign_id, db.Campaign.status == db.RETRYING)
            .values(status=db.FAILED, failure_reason=reason)
        )
        db.add_event(session, campaign_id, db.RUN_STEP, db.FAILED, reason)


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
    async def approve_campaign(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> CampaignOut:
        engine = request.app.state.engine
        campaign = await _found(engine, campaign_id)
        authorize(user, Action.APPROVE, created_by=campaign.created_by)
        is_claimed = await run_in_threadpool(
            _set_status, engine, campaign_id, db.AWAITING_APPROVAL, db.SENDING
        )
        if not is_claimed:
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


def _register_retry_route(app: FastAPI) -> None:
    @app.post("/campaigns/{campaign_id}/retry", status_code=202)
    async def retry_failed_step(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> CampaignOut:
        """The retry-step action: re-run the step that stopped a failed run."""
        engine = request.app.state.engine
        campaign = await _found(engine, campaign_id)
        authorize(user, Action.CREATE)
        if not await run_in_threadpool(_claim_retry, engine, campaign_id):
            raise HTTPException(status_code=409, detail="only a failed run can retry its step")
        try:
            handle = request.app.state.temporal.get_workflow_handle(f"campaign-{campaign_id}")
            await handle.signal(RETRY_SIGNAL)
        except Exception:
            await run_in_threadpool(_undo_retry, engine, campaign_id, campaign.failure_reason)
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
        user: BrowserUser,
        last_event_id: Annotated[int, Header(ge=0)] = 0,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        """`after` is for a browser that follows a run again from a known event (after a
        retry): an EventSource cannot set Last-Event-ID itself. The later of the two wins."""
        authorize(user, Action.READ)
        await _found(request.app.state.engine, campaign_id)
        return StreamingResponse(
            _event_stream(request.app.state.engine, campaign_id, max(last_event_id, after)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def _add_activity_routes(app: FastAPI, settings: Settings) -> None:
    register_webhook_routes(app, settings.marketo_webhook_secret)

    @app.get("/campaigns/{campaign_id}/activity")
    async def campaign_activity(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> list[ActivityOut]:
        authorize(user, Action.READ)
        await _found(request.app.state.engine, campaign_id)
        return await run_in_threadpool(activities, request.app.state.engine, campaign_id)


def _add_preview_route(app: FastAPI) -> None:
    @app.get("/campaigns/{campaign_id}/preview", response_class=HTMLResponse)
    async def preview_email(
        campaign_id: uuid.UUID, request: Request, user: BrowserUser
    ) -> HTMLResponse:
        authorize(user, Action.READ)
        campaign = await _found(request.app.state.engine, campaign_id)
        if campaign.draft is None:
            raise HTTPException(status_code=409, detail="campaign has no draft yet")
        try:
            html = await run_in_threadpool(render_email, campaign.draft)
        except EmailTooLarge as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return HTMLResponse(html)


def _add_campaign_routes(app: FastAPI) -> None:
    @app.get("/me")
    def me(user: CurrentUser) -> Me:
        return Me(subject=user.subject, email=user.email, team=user.team, roles=sorted(user.roles))

    @app.get("/campaigns")
    async def list_campaigns(request: Request, user: CurrentUser) -> list[CampaignOut]:
        authorize(user, Action.READ)
        return await run_in_threadpool(_list, request.app.state.engine)

    @app.post("/campaigns", status_code=201)
    async def create_campaign(
        body: NewCampaign, request: Request, user: CurrentUser
    ) -> CampaignOut:
        authorize(user, Action.CREATE)
        engine = request.app.state.engine
        name, version, dag = await _pinned(engine, body.workflow)
        campaign = db.Campaign(
            id=uuid.uuid4(),
            report=body.report,
            team=user.team,
            created_by=user.subject,
            status=db.DRAFTING,
            workflow_name=name,
            workflow_version=version,
            dag=dag,
        )
        created = await run_in_threadpool(_insert, engine, campaign)
        await request.app.state.temporal.start_workflow(
            WORKFLOW_NAME,
            args=[str(created.id), body.report, dag],
            id=f"campaign-{created.id}",
            task_queue=TASK_QUEUE,
        )
        return created

    @app.get("/campaigns/{campaign_id}")
    async def get_campaign(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> CampaignOut:
        authorize(user, Action.READ)
        return await _found(request.app.state.engine, campaign_id)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = db.make_engine(settings.database_url)
        app.state.verifier = TokenVerifier(settings.oidc_issuer, settings.oidc_client_id)
        app.state.temporal = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        yield
        app.state.engine.dispose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _add_campaign_routes(app)
    _register_approval_route(app)
    _register_retry_route(app)
    _add_event_routes(app)
    _add_activity_routes(app, settings)
    _add_preview_route(app)
    register_workflow_routes(app)

    return app
