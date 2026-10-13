"""The team dashboard: every campaign of the team with its status, cost, quality score and
click rate, oldest first so the list reads as the trend. Quality is the mean judge score of
the run's assets; click rate is clicks per open over both A/B variants (the marketing system
reports no send count to divide by). Both are null until there is something to divide.
Row-level security is the only team filter. The choices are in
docs/decisions/team-dashboard-metrics.md."""

import uuid
from datetime import datetime

from ace_engine import cost, db, row_security
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from campaign_api.auth import Action, CurrentUser, authorize
from campaign_api.webhook_routes import NO_ENGAGEMENT, engagement_by_campaign


class DashboardRow(BaseModel):
    id: uuid.UUID
    # The first line of the campaign's report, as the campaign list shows it.
    title: str
    status: str
    created_at: datetime
    cost_usd: float
    quality_score: float | None
    click_rate: float | None


class DashboardTotals(BaseModel):
    runs: int
    cost_usd: float
    quality_score: float | None
    click_rate: float | None


class DashboardOut(BaseModel):
    campaigns: list[DashboardRow]
    totals: DashboardTotals


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def build(engine: Engine) -> DashboardOut:
    with Session(engine) as session:
        campaigns = list(reversed(db.list_campaigns(session)))
        ids = [c.id for c in campaigns]
        usage = db.usage_by_campaign(session, ids)
        scores = db.asset_scores(session, ids)
        engagement = engagement_by_campaign(session)
    rows: list[DashboardRow] = []
    all_scores: list[int] = []
    for c in campaigns:
        own: list[int] = [s["score"] for s in scores.get(c.id, {}).values() if "score" in s]
        all_scores.extend(own)
        found = engagement.get(c.id, NO_ENGAGEMENT)
        rows.append(
            DashboardRow(
                id=c.id,
                title=c.report.split("\n", 1)[0] or str(c.id),
                status=c.status,
                created_at=c.created_at,
                cost_usd=cost.to_dollars(sum(u.cost_micros for u in usage.get(c.id, []))),
                quality_score=_ratio(sum(own), len(own)),
                click_rate=_ratio(found.clicks, found.opens),
            )
        )
    opens_all = sum(e.opens for e in engagement.values())
    clicks_all = sum(e.clicks for e in engagement.values())
    return DashboardOut(
        campaigns=rows,
        totals=DashboardTotals(
            runs=len(rows),
            cost_usd=sum(r.cost_usd for r in rows),
            quality_score=_ratio(sum(all_scores), len(all_scores)),
            click_rate=_ratio(clicks_all, opens_all),
        ),
    )


def register_dashboard_routes(app: FastAPI) -> None:
    @app.get("/dashboard")
    async def dashboard(request: Request, user: CurrentUser) -> DashboardOut:
        authorize(user, Action.READ)
        engine = row_security.for_team(request.app.state.engine, user.team)
        return await run_in_threadpool(build, engine)
