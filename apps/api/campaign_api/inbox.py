"""The approval inbox: the assets that wait for the signed-in approver's team, and the
approver's decision on each one.

Approving every asset of a campaign approves the campaign and it sends. Rejecting one with a
comment sends that asset back to the writer Session that made it; the rest stay as they
are. Row-level security is the only team filter: another team's campaign is not visible here."""

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from ace_engine import assets, db, row_security, telemetry
from ace_engine.settings import APPROVE_SIGNAL, REJECT_ASSET_SIGNAL
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, StringConstraints
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

from campaign_api.auth import Action, CurrentUser, User, authorize

SERVICE = "campaign-api"
MAX_COMMENT_CHARS = 2_000
TITLE_CHARS = 120
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_COMMENT_CHARS)]
RejectComment = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_COMMENT_CHARS)
]


class ReviewFlag(BaseModel):
    check: str
    detail: str


class AssetOut(BaseModel):
    campaign_id: uuid.UUID
    title: str
    team: str
    created_by: str
    step: str
    # The API path that renders the asset; None when only its text can be shown.
    preview_url: str | None
    output: Any
    # What the brand reviewer still flags on this asset after its fix rounds.
    flags: list[ReviewFlag]
    # What the judge scored the asset and why; None when it was not judged.
    score: int | None = None
    score_reason: str | None = None


class Approval(BaseModel):
    comment: Comment = ""


class Rejection(BaseModel):
    comment: RejectComment


class DecisionOut(BaseModel):
    campaign_id: uuid.UUID
    step: str
    decision: Literal["approved", "rejected"]
    comment: str
    campaign_status: str


@dataclass(frozen=True)
class AssetDecision:
    """One approver's decision on one asset of a campaign."""

    campaign_id: uuid.UUID
    step: str
    decision: Literal["approved", "rejected"]
    comment: str


@dataclass(frozen=True)
class Decided:
    """The outcome of a decision: whether it settled the campaign (or sent the asset back)
    and so needs a signal to the run."""

    campaign_status: str
    should_signal: bool


def _title(report: str) -> str:
    line = next((ln.strip() for ln in report.splitlines() if ln.strip()), "")
    return line[:TITLE_CHARS]


def _inbox(engine: Engine, user: User) -> list[AssetOut]:
    with Session(engine) as session:
        waiting = db.waiting_campaigns(session, user.subject)
        ids = [c.id for c in waiting]
        all_outputs = db.outputs_by_campaign(session, ids)
        all_approved = db.approved_by_campaign(session, ids)
        all_flags = db.review_flags_by_campaign(session, ids)
        all_scores = db.asset_scores(session, ids)
        items: list[AssetOut] = []
        for campaign in waiting:
            outputs = all_outputs.get(campaign.id, {})
            approved = all_approved.get(campaign.id, set())
            flags = {e.step: e.reason for e in all_flags.get(campaign.id, [])}
            scores = all_scores.get(campaign.id, {})
            for step in assets.asset_steps(campaign.dag):
                if step in approved or step not in outputs:
                    continue
                items.append(
                    AssetOut(
                        campaign_id=campaign.id,
                        title=_title(campaign.report),
                        team=campaign.team,
                        created_by=campaign.created_by,
                        step=step,
                        preview_url=assets.preview_path(campaign.id, step),
                        output=outputs[step],
                        flags=[ReviewFlag(**f) for f in json.loads(flags.get(step) or "[]")],
                        score=scores.get(step, {}).get("score"),
                        score_reason=scores.get(step, {}).get("reason"),
                    )
                )
        return items


def _decide(engine: Engine, user: User, asked: AssetDecision) -> Decided:
    """Record the decision in one transaction that holds the campaign's row, so two
    approvers deciding at once settle in order."""
    campaign_id, step, comment = asked.campaign_id, asked.step, asked.comment
    with Session(engine) as session, session.begin():
        campaign = session.get(db.Campaign, campaign_id, with_for_update=True)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        authorize(user, Action.APPROVE, created_by=campaign.created_by)
        if step not in assets.asset_steps(campaign.dag):
            raise HTTPException(status_code=404, detail="asset not found")
        approved = db.approved_steps(session, campaign_id)
        if campaign.status != db.AWAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="campaign is not waiting for approval")
        if step in approved:
            raise HTTPException(status_code=409, detail="asset is already approved")
        if asked.decision == db.ASSET_REJECTED:
            campaign.status = db.DRAFTING
            db.add_event(session, campaign_id, db.RUN_STEP, db.DRAFTING)
            db.add_event(session, campaign_id, step, db.ASSET_REJECTED, comment)
            return Decided(campaign.status, should_signal=True)
        session.add(
            db.AssetApproval(
                campaign_id=campaign_id, step=step, approved_by=user.subject, comment=comment
            )
        )
        db.add_event(session, campaign_id, step, db.ASSET_APPROVED, comment)
        is_complete = approved | {step} >= set(assets.asset_steps(campaign.dag))
        if is_complete:
            campaign.status = db.SENDING
        return Decided(campaign.status, should_signal=is_complete)


def _undo(engine: Engine, asked: AssetDecision) -> None:
    """The run could not be signalled: put the campaign back as it was before the decision."""
    campaign_id, step = asked.campaign_id, asked.step
    with Session(engine) as session, session.begin():
        campaign = session.get_one(db.Campaign, campaign_id, with_for_update=True)
        campaign.status = db.AWAITING_APPROVAL
        if asked.decision == db.ASSET_APPROVED:
            approval = session.get(db.AssetApproval, (campaign_id, step))
            if approval is not None:
                session.delete(approval)


async def _signal(temporal: Client, asked: AssetDecision) -> None:
    handle = temporal.get_workflow_handle(f"campaign-{asked.campaign_id}")
    if asked.decision == db.ASSET_REJECTED:
        with telemetry.span(SERVICE, "campaign.reject_asset"):
            await handle.signal(REJECT_ASSET_SIGNAL, args=[asked.step, asked.comment])
    else:
        with telemetry.span(SERVICE, "campaign.approve"):
            await handle.signal(APPROVE_SIGNAL)


async def _decision(request: Request, user: User, asked: AssetDecision) -> DecisionOut:
    engine = request.app.state.engine
    team_engine = row_security.for_team(engine, user.team)
    decided = await run_in_threadpool(_decide, team_engine, user, asked)
    if decided.should_signal:
        try:
            await _signal(request.app.state.temporal, asked)
        except Exception:
            await run_in_threadpool(_undo, engine, asked)
            raise
    return DecisionOut(
        campaign_id=asked.campaign_id,
        step=asked.step,
        decision=asked.decision,
        comment=asked.comment,
        campaign_status=decided.campaign_status,
    )


def register_inbox_routes(app: FastAPI) -> None:
    @app.get("/inbox")
    async def inbox(request: Request, user: CurrentUser) -> list[AssetOut]:
        authorize(user, Action.APPROVE)
        engine = row_security.for_team(request.app.state.engine, user.team)
        return await run_in_threadpool(_inbox, engine, user)

    @app.post("/campaigns/{campaign_id}/assets/{step}/approve")
    async def approve_asset(
        campaign_id: uuid.UUID, step: str, body: Approval, request: Request, user: CurrentUser
    ) -> DecisionOut:
        return await _decision(
            request, user, AssetDecision(campaign_id, step, "approved", body.comment)
        )

    @app.post("/campaigns/{campaign_id}/assets/{step}/reject")
    async def reject_asset(
        campaign_id: uuid.UUID, step: str, body: Rejection, request: Request, user: CurrentUser
    ) -> DecisionOut:
        return await _decision(
            request, user, AssetDecision(campaign_id, step, "rejected", body.comment)
        )
