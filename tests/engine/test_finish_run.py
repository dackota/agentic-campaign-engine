"""A run that ends is `sent` when a publish step sent it and `finished` when nothing was
published, and its run events say so."""

import pytest
from ace_engine import db
from campaign_worker.activities import Activities
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.seed import add_campaign
from tests.support.settings import unit_settings


@pytest.mark.parametrize(
    ("receipt", "ended_as"),
    [(None, db.FINISHED), ("receipt-1", db.SENT)],
    ids=["no receipt", "receipt"],
)
def test_a_run_ends_sent_with_a_receipt_and_finished_without_one(
    sqlite_engine: Engine, receipt: str | None, ended_as: str
) -> None:
    campaign_id = add_campaign(sqlite_engine, status=db.DRAFTING, receipt=receipt)

    Activities(unit_settings(), sqlite_engine).finish_run(str(campaign_id))

    with Session(sqlite_engine) as session:
        campaign = session.get_one(db.Campaign, campaign_id)
        events = session.scalars(select(db.RunEvent).where(db.RunEvent.campaign_id == campaign_id))
        assert campaign.status == ended_as
        assert [(e.step, e.status) for e in events] == [(db.RUN_STEP, ended_as)]
