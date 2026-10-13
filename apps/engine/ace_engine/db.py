"""Campaign storage in Postgres."""

import json
import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import TypeEngine, UserDefinedType

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
# An asset the judge scored; the reason is JSON with the score and the judge's reason.
SCORED = "scored"
RUN_STEP = "run"
EMAIL_DRAFT_STEP = "email_draft"
STEP_STARTED = "started"
STEP_SUCCEEDED = "succeeded"
# An agent step read through an MCP tool; the event's reason is the tool's name.
TOOL_READ = "tool_read"
STEP_FAILED = "failed"
# Run events for an approver's per-asset decisions: the comment is the event's reason.
ASSET_APPROVED = "approved"
ASSET_REJECTED = "rejected"
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
    # Whether the run reuses saved agent step results (the step cache).
    use_step_cache: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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


class AssetSession(Base):
    """The sessions the agent issued for a writer step, one per reply (variant). A rejected
    asset goes back to these, so the writer keeps its conversation."""

    __tablename__ = "asset_sessions"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id"), primary_key=True
    )
    step: Mapped[str] = mapped_column(String(40), primary_key=True)
    variant: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_session: Mapped[str] = mapped_column(String(200))


class AssetApproval(Base):
    """An approver's approval of one asset (a writer step's output), once per asset."""

    __tablename__ = "asset_approvals"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id"), primary_key=True
    )
    step: Mapped[str] = mapped_column(String(40), primary_key=True)
    approved_by: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str] = mapped_column(Text, default="")
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
    # The step reused a saved result, so it used no tokens.
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StepCacheEntry(Base):
    """A saved agent step result, found again by the step type, the agent revision digest and
    the hash of the input. Kept per team."""

    __tablename__ = "step_cache"

    team: Mapped[str] = mapped_column(String(100), primary_key=True)
    step_type: Mapped[str] = mapped_column(String(80), primary_key=True)
    agent_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    output: Mapped[Any] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(100))
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


class Alert(Base):
    """An alert Grafana raised, kept once per fingerprint. Firing alerts show as the in-app
    banner; a resolved one stays as history."""

    __tablename__ = "alerts"

    fingerprint: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# A learning's embedding has this many numbers: the stand-in's size and the size the
# gateway is asked for (docs/decisions/learnings-store.md).
EMBEDDING_DIMENSIONS = 256
# One process creates the vector extension at a time: the API and the worker start together.
_EXTENSION_LOCK = 4_040_041


class _PgVector(UserDefinedType[list[float]]):
    """pgvector's `vector(n)` column type."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: object) -> str:
        return f"vector({self.dimensions})"


class Embedding(TypeDecorator[list[float]]):
    """A vector in pgvector on Postgres; its text form (`[0.1,0.2]`) anywhere else, so an
    SQLite test database still builds every table."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(EMBEDDING_DIMENSIONS))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return "[" + ",".join(repr(float(x)) for x in value) + "]"

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:  # noqa: ANN401  the driver's text
        if value is None:
            return None
        return [float(x) for x in str(value).strip("[]").split(",") if x]


class Learning(Base):
    """A called A/B winner kept for the agents: the winning lines, why they won, the
    numbers, and an embedding to search by. One per campaign."""

    __tablename__ = "learnings"
    __table_args__ = (UniqueConstraint("campaign_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id"))
    text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(Embedding)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # When an approver deleted it. The row stays, hidden from the view and the search, so
    # the campaign's later opens do not make the learning again.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


def save_asset_sessions(
    session: Session, campaign_id: uuid.UUID, step: str, agent_sessions: Collection[str]
) -> None:
    """Keep the sessions the agent issued for a writer step, replacing an earlier run's."""
    for variant, agent_session in enumerate(agent_sessions):
        session.merge(
            AssetSession(
                campaign_id=campaign_id, step=step, variant=variant, agent_session=agent_session
            )
        )


def asset_sessions(engine: Engine, campaign_id: uuid.UUID, step: str) -> tuple[str, ...]:
    """The agent sessions of a writer step, in reply order; empty when none were kept."""
    with Session(engine) as session:
        return tuple(
            session.scalars(
                select(AssetSession.agent_session)
                .where(AssetSession.campaign_id == campaign_id, AssetSession.step == step)
                .order_by(AssetSession.variant)
            )
        )


def rejection_count(engine: Engine, campaign_id: uuid.UUID, step: str) -> int:
    """How many times approvers have sent this step's asset back."""
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(RunEvent)
                .where(
                    RunEvent.campaign_id == campaign_id,
                    RunEvent.step == step,
                    RunEvent.status == ASSET_REJECTED,
                )
            )
            or 0
        )


def waiting_campaigns(session: Session, excluding_creator: str) -> list[Campaign]:
    """The campaigns that wait for approval, oldest first, left out the ones the named user
    created (nobody approves their own). Row-level security limits them to the user's team."""
    return list(
        session.scalars(
            select(Campaign)
            .where(
                Campaign.status == AWAITING_APPROVAL,
                Campaign.created_by != excluding_creator,
            )
            .order_by(Campaign.created_at)
        )
    )


def outputs_of(session: Session, campaign_id: uuid.UUID) -> dict[str, Any]:
    """What each of the campaign's agent steps produced, by step."""
    return outputs_by_campaign(session, [campaign_id]).get(campaign_id, {})


def outputs_by_campaign(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """`outputs_of` for these campaigns, in one query."""
    found: dict[uuid.UUID, dict[str, Any]] = {}
    rows = session.scalars(select(StepOutput).where(StepOutput.campaign_id.in_(campaign_ids)))
    for row in rows:
        found.setdefault(row.campaign_id, {})[row.step] = row.output
    return found


def approved_steps(session: Session, campaign_id: uuid.UUID) -> set[str]:
    return approved_by_campaign(session, [campaign_id]).get(campaign_id, set())


def approved_by_campaign(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """The approved steps of these campaigns, in one query."""
    found: dict[uuid.UUID, set[str]] = {}
    rows = session.execute(
        select(AssetApproval.campaign_id, AssetApproval.step).where(
            AssetApproval.campaign_id.in_(campaign_ids)
        )
    )
    for campaign_id, step in rows:
        found.setdefault(campaign_id, set()).add(step)
    return found


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
    one per step, from the step's latest run only. A step that started again (a retry, or a
    redo after a rejection) drops the flags of the run before it."""
    return review_flags_by_campaign(session, [campaign_id]).get(campaign_id, [])


def review_flags_by_campaign(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[RunEvent]]:
    """`review_flags` of these campaigns, in one query, each list in event order."""
    events = session.scalars(
        select(RunEvent)
        .where(
            RunEvent.campaign_id.in_(campaign_ids),
            RunEvent.status.in_((FLAGGED, STEP_STARTED)),
        )
        .order_by(RunEvent.seq)
    )
    latest: dict[uuid.UUID, dict[str, RunEvent]] = {}
    for event in events:
        steps = latest.setdefault(event.campaign_id, {})
        if event.status == STEP_STARTED:
            steps.pop(event.step, None)
        else:
            steps[event.step] = event
    return {
        campaign_id: sorted(steps.values(), key=lambda e: e.seq)
        for campaign_id, steps in latest.items()
    }


def asset_scores(
    session: Session, campaign_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[str, dict[str, Any]]]:
    """The judge's latest score and reason per asset step, by campaign."""
    events = session.scalars(
        select(RunEvent)
        .where(RunEvent.campaign_id.in_(campaign_ids), RunEvent.status == SCORED)
        .order_by(RunEvent.seq)
    )
    found: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for event in events:
        found.setdefault(event.campaign_id, {})[event.step] = json.loads(event.reason or "{}")
    return found


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
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _EXTENSION_LOCK})
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    return engine
