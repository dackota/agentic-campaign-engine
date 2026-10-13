"""The Campaign API: create a campaign from a threat report on a saved workflow, read it
back with its draft and the steps of the workflow it pinned.

Every route but /healthz and the signed webhooks needs a signed-in user; `auth` holds the
role rules."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Annotated, Any, Literal

import httpx
from ace_engine import cost, db, learnings, row_security, telemetry
from ace_engine import dag as graph
from ace_engine.settings import (
    APPROVE_SIGNAL,
    RAISE_BUDGET_SIGNAL,
    RETRY_SIGNAL,
    TASK_QUEUE,
    WORKFLOW_NAME,
    Settings,
)
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from opentelemetry import trace
from pydantic import BaseModel, Field, StringConstraints
from render_service import assets
from render_service.email import EmailTooLarge, render_email
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

from campaign_api.ab_result import NO_DECISION, AbResult, decide
from campaign_api.alerts import register_alert_routes
from campaign_api.auth import (
    Action,
    BrowserUser,
    CurrentUser,
    TokenVerifier,
    User,
    authorize,
)
from campaign_api.budget import BudgetUsd, CostOut, NewBudget, budget_usd, set_budget
from campaign_api.dashboard import register_dashboard_routes
from campaign_api.inbox import register_inbox_routes
from campaign_api.learning_routes import register_learning_routes
from campaign_api.trace_middleware import install_campaign_trace
from campaign_api.trace_middleware import remember as remember_trace
from campaign_api.webhook_routes import (
    ActivityOut,
    activities,
    engagement_by_variant,
    register_webhook_routes,
    register_workfront_routes,
)
from campaign_api.workflows import (
    NAME_PATTERN,
    latest_version,
    register_workflow_routes,
    seed_default_workflow,
)

logger = logging.getLogger(__name__)
MAX_REPORT_CHARS = 100_000
SERVICE = "campaign-api"
EVENT_POLL_SECONDS = 0.1
FINAL_STATES = {db.AWAITING_APPROVAL, db.FAILED, db.SENT, db.FINISHED, db.BUDGET_PAUSED}
# A run in one of these has ended; no signal reaches it.
ENDED_STATES = {db.SENT, db.FINISHED}
Report = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=MAX_REPORT_CHARS)
]


class NewCampaign(BaseModel):
    report: Report
    # The saved workflow to run, at its latest version; None runs the default workflow.
    workflow: str | None = Field(default=None, pattern=NAME_PATTERN)
    # What the run may spend on models, in dollars; None is no limit.
    budget_usd: BudgetUsd | None = None
    # Reuse the saved result of an agent step this team has run before with the same agent
    # revision and input (docs/decisions/step-cache.md). Off unless asked.
    use_step_cache: bool = False

    def model_post_init(self, _context: object) -> None:
        if not self.report.strip():
            raise ValueError("report must not be blank")


class ReceiptOut(BaseModel):
    target: str
    receipt_id: str
    url: str


class FlagOut(BaseModel):
    """A step the brand reviewer could not fix in its rounds, left for a human."""

    step: str
    issues: list[dict[str, Any]]


class ScoreOut(BaseModel):
    """The judge's score for one asset and its reason."""

    step: str
    score: int
    reason: str


class AbResultOut(BaseModel):
    status: Literal["winner", "no_decision"]
    winner: str | None
    confidence: float | None

    @classmethod
    def of(cls, result: AbResult) -> "AbResultOut":
        status: Literal["winner", "no_decision"] = (
            "no_decision" if result.winner is None else "winner"
        )
        return cls(status=status, winner=result.winner, confidence=result.confidence)


@dataclass(frozen=True)
class RunDetail:
    """What a run's view adds to the campaign row: engagement, reviewer flags, step usage."""

    engagement: dict[str, dict[str, int]] = field(default_factory=dict)
    flags: list[FlagOut] = field(default_factory=list)
    scores: list[ScoreOut] = field(default_factory=list)
    usage: list[db.StepUsage] = field(default_factory=list)


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
    # One receipt per publish target; `task_status` is the Workfront task's latest status.
    receipts: list[ReceiptOut]
    task_status: str | None
    workflow: str | None
    workflow_version: int | None
    steps: list[dict[str, Any]]
    # The DAG's edges, so the run view can draw the graph.
    edges: list[dict[str, str]] = Field(default_factory=list)
    # Opens and clicks per variant label, from the marketing system's activity webhooks.
    engagement: dict[str, dict[str, int]] = Field(default_factory=dict)
    # What the brand reviewer still flags after its fix rounds, by step.
    flags: list[FlagOut] = Field(default_factory=list)
    # What the judge scored each asset, with its reason.
    scores: list[ScoreOut] = Field(default_factory=list)
    ab_result: AbResultOut = Field(default_factory=lambda: AbResultOut.of(NO_DECISION))
    budget_usd: float | None = None
    # Tokens and cost per agent step and in total.
    cost: CostOut = Field(default_factory=CostOut)

    @classmethod
    def of(
        cls,
        c: db.Campaign,
        receipts: list[db.Receipt],
        task_status: str | None,
        detail: RunDetail | None = None,
    ) -> "CampaignOut":
        detail = detail or RunDetail()
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
            receipts=[
                ReceiptOut(target=r.target, receipt_id=r.receipt_id, url=r.url) for r in receipts
            ],
            task_status=task_status,
            workflow=c.workflow_name,
            workflow_version=c.workflow_version,
            steps=[
                {**s, "idempotency_key": graph.step_key(str(c.id), s["id"])}
                for s in graph.ordered(c.dag)
            ],
            edges=list(c.dag.get("edges", [])),
            engagement=detail.engagement,
            flags=detail.flags,
            scores=detail.scores,
            ab_result=AbResultOut.of(decide(detail.engagement)),
            budget_usd=budget_usd(c),
            cost=CostOut.of(detail.usage),
        )


class Me(BaseModel):
    subject: str
    email: str
    team: str | None
    roles: list[str]


def _team_engine(request: Request, user: User) -> Engine:
    """The database as the signed-in user's team sees it: row-level security shows the
    request only its team's rows, so no query here names a team."""
    return row_security.for_team(request.app.state.engine, user.team)


def _insert(engine: Engine, campaign: db.Campaign, traceparent: str | None) -> CampaignOut:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(campaign)
        session.flush()
        if traceparent is not None:
            session.add(db.CampaignTrace(campaign_id=campaign.id, traceparent=traceparent))
        return CampaignOut.of(campaign, [], None)


def _list(engine: Engine) -> list[CampaignOut]:
    with Session(engine) as session:
        campaigns = db.list_campaigns(session)
        ids = [c.id for c in campaigns]
        receipts = db.receipts_by_campaign(session, ids)
        statuses = db.task_statuses(session, ids)
        usage = db.usage_by_campaign(session, ids)
        return [
            CampaignOut.of(
                c,
                receipts.get(c.id, []),
                statuses.get(c.id),
                RunDetail(usage=usage.get(c.id, [])),
            )
            for c in campaigns
        ]


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
        if campaign is None:
            return None
        receipts = db.receipts_by_campaign(session, [campaign_id])
        statuses = db.task_statuses(session, [campaign_id])
        return CampaignOut.of(
            campaign,
            receipts.get(campaign_id, []),
            statuses.get(campaign_id),
            RunDetail(
                engagement=engagement_by_variant(session, campaign_id),
                flags=[
                    FlagOut(step=e.step, issues=json.loads(e.reason or "[]"))
                    for e in db.review_flags(session, campaign_id)
                ],
                scores=[
                    ScoreOut(step=step, **found)
                    for step, found in db.asset_scores(session, [campaign_id])
                    .get(campaign_id, {})
                    .items()
                ],
                usage=db.usage_by_campaign(session, [campaign_id]).get(campaign_id, []),
            ),
        )


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
        engine = _team_engine(request, user)
        campaign = await _found(engine, campaign_id)
        authorize(user, Action.APPROVE, created_by=campaign.created_by)
        is_claimed = await run_in_threadpool(
            _set_status, engine, campaign_id, db.AWAITING_APPROVAL, db.SENDING
        )
        if not is_claimed:
            raise HTTPException(status_code=409, detail="campaign is not waiting for approval")
        try:
            handle = request.app.state.temporal.get_workflow_handle(f"campaign-{campaign_id}")
            with telemetry.span(SERVICE, "campaign.approve"):
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
        engine = _team_engine(request, user)
        campaign = await _found(engine, campaign_id)
        authorize(user, Action.CREATE)
        if not await run_in_threadpool(_claim_retry, engine, campaign_id):
            raise HTTPException(status_code=409, detail="only a failed run can retry its step")
        try:
            handle = request.app.state.temporal.get_workflow_handle(f"campaign-{campaign_id}")
            with telemetry.span(SERVICE, "campaign.retry"):
                await handle.signal(RETRY_SIGNAL)
        except Exception:
            await run_in_threadpool(_undo_retry, engine, campaign_id, campaign.failure_reason)
            raise
        return await _found(engine, campaign_id)


def _register_budget_route(app: FastAPI) -> None:
    @app.post("/campaigns/{campaign_id}/budget")
    async def raise_budget(
        campaign_id: uuid.UUID, body: NewBudget, request: Request, user: CurrentUser
    ) -> CampaignOut:
        """Set a new budget; a run paused at its budget goes on. The new budget must be
        above what the campaign has spent, or the run would pause again at once."""
        engine = _team_engine(request, user)
        campaign = await _found(engine, campaign_id)
        authorize(user, Action.CREATE)
        if campaign.status in ENDED_STATES:
            raise HTTPException(status_code=409, detail="the run has ended")
        change = await run_in_threadpool(
            set_budget, engine, campaign_id, cost.to_micros(body.budget_usd)
        )
        if change.too_low_for is not None:
            spent = cost.to_dollars(change.too_low_for)
            raise HTTPException(
                status_code=422, detail=f"the budget must be above the ${spent:.4f} spent"
            )
        try:
            handle = request.app.state.temporal.get_workflow_handle(f"campaign-{campaign_id}")
            await handle.signal(RAISE_BUDGET_SIGNAL)
        except Exception:
            if change.was_paused:
                await run_in_threadpool(
                    _set_status, engine, campaign_id, db.DRAFTING, db.BUDGET_PAUSED
                )
            raise
        return await _found(engine, campaign_id)


def _sse(event: db.RunEvent) -> str:
    data = {
        "seq": event.seq,
        "step": event.step,
        "status": event.status,
        "reason": event.reason,
        "session": event.session,
        "tokens": event.tokens,
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
        await _found(_team_engine(request, user), campaign_id)
        return StreamingResponse(
            _event_stream(_team_engine(request, user), campaign_id, max(last_event_id, after)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


class StepOutputOut(BaseModel):
    step: str
    session: str
    output: Any


def _add_step_routes(app: FastAPI) -> None:
    @app.get("/campaigns/{campaign_id}/steps")
    async def campaign_steps(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> list[StepOutputOut]:
        authorize(user, Action.READ)
        engine = _team_engine(request, user)
        await _found(engine, campaign_id)
        rows = await run_in_threadpool(db.step_outputs, engine, campaign_id)
        return [StepOutputOut(step=r.step, session=r.session, output=r.output) for r in rows]


def _add_activity_routes(app: FastAPI, settings: Settings) -> None:
    register_webhook_routes(app, settings.marketo_webhook_secret)
    if settings.has_workfront:
        register_workfront_routes(app, settings.workfront_webhook_secret)

    @app.get("/campaigns/{campaign_id}/activity")
    async def campaign_activity(
        campaign_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> list[ActivityOut]:
        authorize(user, Action.READ)
        await _found(_team_engine(request, user), campaign_id)
        return await run_in_threadpool(activities, _team_engine(request, user), campaign_id)


def _add_preview_route(app: FastAPI) -> None:
    @app.get("/campaigns/{campaign_id}/preview", response_class=HTMLResponse)
    async def preview_email(
        campaign_id: uuid.UUID, request: Request, user: BrowserUser
    ) -> HTMLResponse:
        authorize(user, Action.READ)
        campaign = await _found(_team_engine(request, user), campaign_id)
        if campaign.draft is None:
            raise HTTPException(status_code=409, detail="campaign has no draft yet")
        try:
            html = await run_in_threadpool(render_email, campaign.draft)
        except EmailTooLarge as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return HTMLResponse(html)


PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Preview kind -> (steps whose output it renders, renderer, content type).
_ASSET_KINDS: Mapping[str, tuple[tuple[str, ...], Callable[..., str | bytes], str]] = (
    MappingProxyType(
        {
            "one-pager": (("one_pager",), assets.render_one_pager_pdf, "application/pdf"),
            "deck": (("one_pager", "landing_page"), assets.render_deck_pptx, PPTX_TYPE),
            "landing-page": (("landing_page",), assets.render_landing_page_html, "text/html"),
            "cards": (("design",), assets.render_cards_html, "text/html"),
            "social": (("social",), assets.render_social_html, "text/html"),
            "graphic": (("one_pager",), assets.render_graphic_svg, "image/svg+xml"),
        }
    )
)


def _add_asset_preview_route(app: FastAPI) -> None:
    @app.get("/campaigns/{campaign_id}/preview/{kind}")
    async def preview_asset(
        campaign_id: uuid.UUID, kind: str, request: Request, user: BrowserUser
    ) -> Response:
        """The brand-rendered one-pager (PDF), deck (PPTX), landing page or social posts
        (HTML), or graphic (SVG), made from what the campaign's writer steps produced."""
        authorize(user, Action.READ)
        if kind not in _ASSET_KINDS:
            raise HTTPException(status_code=404, detail="unknown asset kind")
        engine = _team_engine(request, user)
        await _found(engine, campaign_id)
        needed, render, media_type = _ASSET_KINDS[kind]
        rows = await run_in_threadpool(db.step_outputs, engine, campaign_id)
        outputs = {r.step: r.output for r in rows}
        if not all(step in outputs for step in needed):
            raise HTTPException(status_code=409, detail=f"campaign has no {kind} content yet")
        try:
            content = await run_in_threadpool(render, *(outputs[step] for step in needed))
        except (KeyError, TypeError) as e:
            logger.exception("malformed stored %s content for campaign %s", kind, campaign_id)
            raise HTTPException(
                status_code=422, detail=f"stored {kind} content is malformed"
            ) from e
        return Response(content, media_type=media_type)


def _new_campaign(
    body: NewCampaign, user: User, name: str | None, version: int | None, dag: dict[str, Any]
) -> db.Campaign:
    """A drafting campaign that runs `dag`, version `version` of workflow `name`."""
    return db.Campaign(
        id=uuid.uuid4(),
        report=body.report,
        team=user.team,
        created_by=user.subject,
        status=db.DRAFTING,
        workflow_name=name,
        workflow_version=version,
        dag=dag,
        budget_micros=None if body.budget_usd is None else cost.to_micros(body.budget_usd),
        use_step_cache=body.use_step_cache,
    )


def _add_campaign_routes(app: FastAPI) -> None:
    @app.get("/me")
    def me(user: CurrentUser) -> Me:
        return Me(subject=user.subject, email=user.email, team=user.team, roles=sorted(user.roles))

    @app.get("/campaigns")
    async def list_campaigns(request: Request, user: CurrentUser) -> list[CampaignOut]:
        authorize(user, Action.READ)
        return await run_in_threadpool(_list, _team_engine(request, user))

    @app.post("/campaigns", status_code=201)
    async def create_campaign(
        body: NewCampaign, request: Request, user: CurrentUser
    ) -> CampaignOut:
        authorize(user, Action.CREATE)
        engine = _team_engine(request, user)
        name, version, dag = await _pinned(engine, body.workflow)
        campaign = _new_campaign(body, user, name, version, dag)
        # This request's span is the root of the campaign's trace: keep it for later requests,
        # and the workflow started below carries it through Temporal.
        trace.get_current_span().set_attribute(telemetry.CAMPAIGN_ATTRIBUTE, str(campaign.id))
        traceparent = telemetry.current_traceparent()
        created = await run_in_threadpool(_insert, engine, campaign, traceparent)
        if traceparent is not None:
            remember_trace(campaign.id, user.team, traceparent)
        with telemetry.span(SERVICE, "campaign.start"):
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
        return await _found(_team_engine(request, user), campaign_id)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = db.make_engine(settings.database_url)
        await run_in_threadpool(row_security.install, app.state.engine)
        await run_in_threadpool(seed_default_workflow, app.state.engine)
        embed_client = httpx.Client(timeout=learnings.EMBED_TIMEOUT_SECONDS)
        app.state.embed = learnings.embedder_for(
            settings.depth, settings.embedding_url, settings.embedding_model, embed_client
        )
        app.state.verifier = TokenVerifier(settings.oidc_issuer, settings.oidc_client_id)
        app.state.temporal = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            interceptors=telemetry.temporal_interceptors(),
        )
        yield
        await run_in_threadpool(embed_client.close)
        app.state.engine.dispose()

    app = FastAPI(lifespan=lifespan)
    telemetry.instrument_app(app, SERVICE)
    install_campaign_trace(app, settings)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _add_campaign_routes(app)
    _register_approval_route(app)
    register_inbox_routes(app)
    _register_retry_route(app)
    _register_budget_route(app)
    _add_event_routes(app)
    _add_step_routes(app)
    _add_activity_routes(app, settings)
    register_alert_routes(app, settings)
    _add_preview_route(app)
    _add_asset_preview_route(app)
    register_workflow_routes(app)
    register_learning_routes(app)
    register_dashboard_routes(app)

    return app
