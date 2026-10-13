"""Each team's step slots: how many of a team's model-calling steps run at once.

A step claims a slot before its model call and gives it back after. A team with every slot
taken waits, while other teams' steps go on, so one team's campaigns cannot take every model
call (docs/decisions/team-step-limit.md). The slots live in Postgres, so every worker replica
counts the same ones. A slot carries a lease: a step whose worker died frees its slot when the
lease ends."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ace_engine import db

# The first key of the advisory lock that makes one team's claims take turns; the second
# is the hash of the team.
_SLOT_LOCK_CLASS = 4_040_056


def claim(
    session: Session,
    campaign_id: uuid.UUID,
    key: str,
    limit: int,
    lease: timedelta,
) -> bool:
    """Take a slot of the campaign's team for the step `key`, for `lease`. True when the
    step holds a slot, a second claim of the same step included; False when the team's
    `limit` slots are all held. Call inside a transaction."""
    team = session.get_one(db.Campaign, campaign_id).team
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_class, hashtext(:team))"),
            {"lock_class": _SLOT_LOCK_CLASS, "team": team},
        )
    now = datetime.now(UTC)
    expires_at = now + lease
    held = session.get(db.StepSlot, key)
    if held is not None:
        held.expires_at = expires_at
        return True
    session.execute(
        delete(db.StepSlot).where(db.StepSlot.team == team, db.StepSlot.expires_at < now)
    )
    in_use = session.scalar(
        select(func.count()).select_from(db.StepSlot).where(db.StepSlot.team == team)
    )
    if (in_use or 0) >= limit:
        return False
    session.add(db.StepSlot(key=key, campaign_id=campaign_id, team=team, expires_at=expires_at))
    return True


def release(session: Session, key: str) -> None:
    """Give back the slot the step `key` holds; nothing when it holds none."""
    session.execute(delete(db.StepSlot).where(db.StepSlot.key == key))
