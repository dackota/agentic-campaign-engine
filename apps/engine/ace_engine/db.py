"""Campaign storage in Postgres."""

import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DRAFTING = "drafting"
AWAITING_APPROVAL = "awaiting_approval"
SENDING = "sending"
SENT = "sent"
FAILED = "failed"
# A failed run the owner asked to retry: it re-runs the step that stopped it.
RETRYING = "retrying"
# A run whose workflow has no publish step ends here.
FINISHED = "finished"
# A run that reached its budget: it waits before its next model step for the owner to
# raise the budget.
BUDGET_PAUSED = "budget_paused"

# Run events: one row per step status change; the step "run" carries the final state.
# A step the brand reviewer gave up on after its fix rounds.
FLAGGED = "flagged"
# A step the brand reviewer sent back to its writer for a fix.
REVIEW_FIX = "review_fix"
RUN_STEP = "run"
EMAIL_DRAFT_STEP = "email_draft"
STEP_STARTED = "started"
STEP_SUCCEEDED = "succeeded"
STEP_FAILED = "failed"
# A failed run the owner asked to retry: it re-runs the step that stopped it.
RETRYING = "retrying"


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report: Mapped[str] = mapped_column(Text)
    # The team and the OIDC subject of the owner who created it (from their token).
    team: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=DRAFTING)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # The A/B test's second email; `draft` is variant A.
    variant_b: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The run pins its workflow: the version it started on and a copy of that DAG.
    # Both are None for a campaign on the built-in default workflow.
    workflow_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dag: Mapped[dict[str, Any]] = mapped_column(JSON)
    # What the owner lets the run spend on models, in micro-dollars; None is no limit.
    budget_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CampaignTrace(Base):
    """The `traceparent` of the request span that created the campaign: the root of its
    trace. Later requests for the campaign join it."""

    __tablename__ = "campaign_traces"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id"), primary_key=True
    )
    traceparent: Mapped[str] = mapped_column(String(100))


class WorkflowVersion(Base):
    """One saved version of a workflow DAG. Versions are never edited, only added."""

    __tablename__ = "workflow_versions"

    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    dag: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id"), index=True)
    step: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The kagent Session the step talked to; None for steps that talk to no agent.
    session: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The tokens an agent step used, on its succeeded event; None everywhere else.
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StepOutput(Base):
    """What an agent step produced, with the session it ran in."""

    __tablename__ = "step_outputs"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id"), primary_key=True
    )
    step: Mapped[str] = mapped_column(String(40), primary_key=True)
    session: Mapped[str] = mapped_column(String(200))
    output: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StepUsage(Base):
    """The cost ledger: the tokens an agent step's model calls used and what they cost.
    One row per step; a re-run of the step replaces it."""

    __tablename__ = "step_usage"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id"), primary_key=True
    )
    step: Mapped[str] = mapped_column(String(40), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    cost_micros: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Activity(Base):
    """One activity webhook from a marketing system, recorded once per (source, event id)."""

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("source", "event_id"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(String(200))
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    variant: Mapped[str] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Receipt(Base):
    """What a publish target gave back for a campaign: its id and a link, once per target."""

    __tablename__ = "receipts"
    __table_args__ = (UniqueConstraint("campaign_id", "target"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id"), index=True)
    target: Mapped[str] = mapped_column(String(40))
    receipt_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)


class TaskStatusEvent(Base):
    """One status webhook for a campaign's task, recorded once per (source, event id)."""

    __tablename__ = "task_status_events"
    __table_args__ = (UniqueConstraint("source", "event_id"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(String(200))
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def add_event(
    session: Session,
    campaign_id: uuid.UUID,
    step: str,
    status: str,
    reason: str | None = None,
) -> RunEvent:
    event = RunEvent(campaign_id=campaign_id, step=step, status=status, reason=reason)
    session.add(event)
    return event


def add_agent_event(
    session: Session,
    campaign_id: uuid.UUID,
    step: str,
    status: str,
    agent_session: str | None,
) -> RunEvent:
    """A run event for an agent step, tagged with the agent session that ran it. The
    caller may set `reason` on the returned event (a review event carries the issues) or,
    once the step has succeeded, the `tokens` it used."""
    event = add_event(session, campaign_id, step, status)
    event.session = agent_session
    return event


def step_outputs(engine: Engine, campaign_id: uuid.UUID) -> list[StepOutput]:
    """What the campaign's agent steps produced, in the order they finished."""
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StepOutput)
                .where(StepOutput.campaign_id == campaign_id)
                .order_by(StepOutput.created_at, StepOutput.step)
            )
        )


def events_after(engine: Engine, campaign_id: uuid.UUID, after_seq: int) -> list[RunEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.campaign_id == campaign_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
            )
        )


def review_flags(session: Session, campaign_id: uuid.UUID) -> list[RunEvent]:
    """The events where a reviewer gave up on a step and flagged it for a human: the latest
    one per step, so a retried step shows one flag."""
    events = session.scalars(
        select(RunEvent)
        .where(RunEvent.campaign_id == campaign_id, RunEvent.status == FLAGGED)
        .order_by(RunEvent.seq)
    )
    latest = {e.step: e for e in events}
    return sorted(latest.values(), key=lambda e: e.seq)


def save_receipt(
    engine: Engine, campaign_id: uuid.UUID, target: str, receipt_id: str, url: str
) -> None:
    """Keep the target's receipt for the campaign; a retried publish writes it only once."""
    with Session(engine) as session, session.begin():
        found = session.scalar(
            select(Receipt).where(Receipt.campaign_id == campaign_id, Receipt.target == target)
        )
        if found is None:
            session.add(
                Receipt(campaign_id=campaign_id, target=target, receipt_id=receipt_id, url=url)
            )
        else:
            found.receipt_id, found.url = receipt_id, url


def receipts_by_campaign(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[Receipt]]:
    """The receipts of these campaigns, in one query, oldest first."""
    found: dict[uuid.UUID, list[Receipt]] = {}
    rows = session.scalars(
        select(Receipt).where(Receipt.campaign_id.in_(campaign_ids)).order_by(Receipt.seq)
    )
    for row in rows:
        found.setdefault(row.campaign_id, []).append(row)
    return found


def task_statuses(session: Session, campaign_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The latest task status of each of these campaigns that has one, in one query."""
    latest = (
        select(func.max(TaskStatusEvent.seq))
        .where(TaskStatusEvent.campaign_id.in_(campaign_ids))
        .group_by(TaskStatusEvent.campaign_id)
    )
    rows = session.execute(
        select(TaskStatusEvent.campaign_id, TaskStatusEvent.status).where(
            TaskStatusEvent.seq.in_(latest)
        )
    )
    return {campaign_id: status for campaign_id, status in rows}


def usage_by_campaign(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[StepUsage]]:
    """The ledger rows of these campaigns, in one query, in the order the steps finished."""
    found: dict[uuid.UUID, list[StepUsage]] = {}
    rows = session.scalars(
        select(StepUsage)
        .where(StepUsage.campaign_id.in_(campaign_ids))
        .order_by(StepUsage.created_at, StepUsage.step)
    )
    for row in rows:
        found.setdefault(row.campaign_id, []).append(row)
    return found


def spent_micros(session: Session, campaign_id: uuid.UUID) -> int:
    """What the campaign's model calls have cost so far."""
    total = session.scalar(
        select(func.coalesce(func.sum(StepUsage.cost_micros), 0)).where(
            StepUsage.campaign_id == campaign_id
        )
    )
    return int(total or 0)


def list_campaigns(session: Session) -> list[Campaign]:
    """Every campaign, newest first."""
    return list(session.scalars(select(Campaign).order_by(Campaign.created_at.desc())))


def campaign_traceparent(engine: Engine, campaign_id: uuid.UUID) -> str | None:
    """The traceparent a campaign's trace is joined by, or None when it has none."""
    with Session(engine) as session:
        return session.scalar(
            select(CampaignTrace.traceparent).where(CampaignTrace.campaign_id == campaign_id)
        )


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine
