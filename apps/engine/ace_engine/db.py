"""Campaign storage in Postgres."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DRAFTING = "drafting"
AWAITING_APPROVAL = "awaiting_approval"
SENDING = "sending"
SENT = "sent"
FAILED = "failed"

# Run events: one row per step status change; the step "run" carries the final state.
RUN_STEP = "run"
EMAIL_DRAFT_STEP = "email_draft"
STEP_STARTED = "started"
STEP_SUCCEEDED = "succeeded"
STEP_FAILED = "failed"


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=DRAFTING)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def add_event(
    session: Session, campaign_id: uuid.UUID, step: str, status: str, reason: str | None = None
) -> None:
    session.add(RunEvent(campaign_id=campaign_id, step=step, status=status, reason=reason))


def events_after(engine: Engine, campaign_id: uuid.UUID, after_seq: int) -> list[RunEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.campaign_id == campaign_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
            )
        )


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine
