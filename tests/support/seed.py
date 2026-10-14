"""Campaign rows for a test that has no running campaign: a row in the database as the
worker would have left it, for the routes and the inbox to read."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ace_engine import db
from ace_engine.default_workflow import default_workflow_dag
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.app import StubVerifier
from tests.support.dag import AWAITING, OWNER, REPORT

DEMAND_GEN = "demand-gen"


@dataclass(frozen=True)
class CampaignSeed:
    """A campaign of `team` made by the demo user `created_by` (an email), with `outputs`
    saved as its steps' outputs."""

    team: str = DEMAND_GEN
    created_by: str = OWNER
    status: str = AWAITING
    report: str = REPORT
    draft: dict[str, Any] | None = None
    variant_b: dict[str, Any] | None = None
    dag: dict[str, Any] = field(default_factory=default_workflow_dag)
    outputs: Mapping[str, Any] = field(default_factory=dict)
    use_step_cache: bool = False
    budget_micros: int | None = None


def seed_campaign(engine: Engine, seed: CampaignSeed = CampaignSeed()) -> uuid.UUID:  # noqa: B008
    """Add the campaign `seed` describes. Returns its id."""
    campaign_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            db.Campaign(
                id=campaign_id,
                report=seed.report,
                team=seed.team,
                created_by=StubVerifier().verify(seed.created_by).subject,
                status=seed.status,
                draft=seed.draft,
                variant_b=seed.variant_b,
                dag=seed.dag,
                use_step_cache=seed.use_step_cache,
                budget_micros=seed.budget_micros,
            )
        )
        session.flush()
        for step_id, output in seed.outputs.items():
            session.add(
                db.StepOutput(
                    campaign_id=campaign_id,
                    step=step_id,
                    session=f"{step_id}-session",
                    output=output,
                )
            )
    return campaign_id
