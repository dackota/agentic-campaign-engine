"""Campaign rows for a test that seeds a database directly instead of calling the API."""

import uuid

from ace_engine import db
from ace_engine.dag import default_dag
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

TEAM = "demand-gen"
OTHER_TEAM = "product-marketing"
OWNER_SUBJECT = "dg-owner"


def add_campaign(engine: Engine, **fields: object) -> uuid.UUID:
    """Insert a drafting campaign of the Demand Gen team on the default workflow; any column
    can be set by keyword. Returns its id."""
    values: dict[str, object] = {
        "report": "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.",
        "team": TEAM,
        "created_by": OWNER_SUBJECT,
        "status": db.DRAFTING,
        "dag": default_dag(),
        **fields,
    }
    campaign_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        session.add(db.Campaign(id=campaign_id, **values))
    return campaign_id


def add_usage(
    engine: Engine, campaign_id: uuid.UUID, step: str, cost_micros: int, **fields: object
) -> None:
    """Insert one step's cost-ledger row."""
    values: dict[str, object] = {
        "model": "scripted-model",
        "input_tokens": 0,
        "output_tokens": 0,
        **fields,
    }
    with Session(engine) as session, session.begin():
        session.add(
            db.StepUsage(campaign_id=campaign_id, step=step, cost_micros=cost_micros, **values)
        )


def campaign_status(engine: Engine, campaign_id: uuid.UUID) -> str:
    with Session(engine) as session:
        return session.get_one(db.Campaign, campaign_id).status


def add_run_event(
    engine: Engine, campaign_id: uuid.UUID, step: str, status: str, reason: str | None = None
) -> int:
    """Append one run event to the campaign's stream; returns its sequence number."""
    with Session(engine) as session, session.begin():
        event = db.add_event(session, campaign_id, step, status, reason)
        session.flush()
        return event.seq
