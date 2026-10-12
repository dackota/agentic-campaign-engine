"""What a campaign's model calls cost, and the owner's budget: the cost the API shows per
step and in total, and the check behind the route that raises a budget."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from ace_engine import cost, db
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# The most a campaign's budget can be, so a typo cannot lift the cap off.
MAX_BUDGET_USD = 10_000
BudgetUsd = Annotated[float, Field(gt=0, le=MAX_BUDGET_USD, allow_inf_nan=False)]


class StepCostOut(BaseModel):
    step: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    # The step reused a saved result instead of calling the agent.
    cache_hit: bool = False

    @classmethod
    def of(cls, row: db.StepUsage) -> "StepCostOut":
        return cls(
            step=row.step,
            model=row.model,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            total_tokens=row.input_tokens + row.output_tokens,
            cost_usd=cost.to_dollars(row.cost_micros),
            cache_hit=bool(row.cache_hit),
        )


class CostOut(BaseModel):
    """The campaign's tokens and cost: the sums of its steps, which are listed too."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    steps: list[StepCostOut] = Field(default_factory=list)

    @classmethod
    def of(cls, rows: list[db.StepUsage]) -> "CostOut":
        input_tokens = sum(r.input_tokens for r in rows)
        output_tokens = sum(r.output_tokens for r in rows)
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            # Summed in whole micro-dollars, so the total is exact.
            cost_usd=cost.to_dollars(sum(r.cost_micros for r in rows)),
            steps=[StepCostOut.of(r) for r in rows],
        )


def budget_usd(campaign: db.Campaign) -> float | None:
    return None if campaign.budget_micros is None else cost.to_dollars(campaign.budget_micros)


class NewBudget(BaseModel):
    budget_usd: BudgetUsd


@dataclass(frozen=True)
class BudgetChange:
    # What the campaign had spent, in micro-dollars, when the new budget was too low.
    too_low_for: int | None = None
    # True when the run was paused at its budget and now drafts again.
    was_paused: bool = False


def set_budget(engine: Engine, campaign_id: uuid.UUID, budget_micros: int) -> BudgetChange:
    """Set the budget when it is above what the campaign has spent, and move a run paused
    at its budget back to drafting. The caller then signals the run."""
    with Session(engine) as session, session.begin():
        # Lock the row so two raises for one campaign apply one at a time.
        campaign = session.get_one(db.Campaign, campaign_id, with_for_update=True)
        spent = db.spent_micros(session, campaign_id)
        if budget_micros <= spent:
            return BudgetChange(too_low_for=spent)
        campaign.budget_micros = budget_micros
        if campaign.status != db.BUDGET_PAUSED:
            return BudgetChange()
        campaign.status = db.DRAFTING
        db.add_event(session, campaign_id, db.RUN_STEP, db.DRAFTING)
        return BudgetChange(was_paused=True)
