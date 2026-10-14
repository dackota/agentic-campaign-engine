"""Rows for tests that read the database or the API on top of it, with no run behind them."""

import uuid
from datetime import UTC, datetime
from typing import Any

from ace_engine import dag as graph
from ace_engine import db
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

TEAM = "demand-gen"
OTHER_TEAM = "product-marketing"
# The subject of a demo user other than the ones a test signs in as.
SOMEONE_ELSE = "someone-else"


def add_campaign(engine: Engine, **columns: Any) -> uuid.UUID:  # noqa: ANN401  any column
    """A campaign row with the given columns over a team's awaiting-approval default; returns
    its id. Its run is not started: only the row exists."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "report": "A threat report\nWith a second line.",
        "team": TEAM,
        "created_by": SOMEONE_ELSE,
        "status": db.AWAITING_APPROVAL,
        "dag": graph.default_dag(),
        "created_at": datetime.now(UTC),
        **columns,
    }
    with Session(engine) as session, session.begin():
        session.add(db.Campaign(**row))
    campaign_id: uuid.UUID = row["id"]
    return campaign_id
