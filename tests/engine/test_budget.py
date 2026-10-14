"""What a campaign's model calls cost as the API shows it, and the owner's budget: the cost
per step and in total, the amounts a budget may be, and the check behind the route that raises
a budget."""

import random
import uuid

import pytest
from ace_engine import cost, db
from campaign_api.budget import MAX_BUDGET_USD, BudgetChange, CostOut, NewBudget, set_budget
from campaign_api.main import NewCampaign
from campaign_worker.activities import Activities
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.campaigns import add_campaign, add_usage, campaign_status
from tests.support.dag import REPORT
from tests.support.settings import unit_settings

SCRIPTED_MODEL = "scripted-model"
SEED = 5
CASES = 200
BAD_BUDGETS = [0, -1, "lots", float("nan"), float("inf"), MAX_BUDGET_USD + 1, None]


def _ledger(engine: Engine, campaign_id: uuid.UUID) -> CostOut:
    with Session(engine) as session:
        return CostOut.of(db.usage_by_campaign(session, [campaign_id]).get(campaign_id, []))


def test_each_step_reports_the_tokens_and_cost_its_replies_used(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine)
    reply = {"input_tokens": 1200, "output_tokens": 300, "model": SCRIPTED_MODEL}
    # The email writer's step makes two replies; the activity books their sum.
    booked = cost.usage_from(reply) + cost.usage_from(reply)

    Activities(unit_settings(), sqlite_engine).save_agent_output(
        str(campaign_id),
        "email_draft",
        {"output": [{}, {}], "session": "s", "usage": booked.as_dict()},
    )

    [step] = _ledger(sqlite_engine, campaign_id).steps
    assert step.model_dump() == {
        "step": "email_draft",
        "model": SCRIPTED_MODEL,
        "input_tokens": 2400,
        "output_tokens": 600,
        "total_tokens": 3000,
        "cost_usd": pytest.approx(0.0162),
        "cache_hit": False,
    }


def test_a_steps_usage_with_only_a_total_is_booked_at_the_output_price(
    sqlite_engine: Engine,
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    two_replies = cost.usage_from({"total_tokens": 700}) + cost.usage_from({"total_tokens": 700})

    Activities(unit_settings(), sqlite_engine).save_agent_output(
        str(campaign_id),
        "email_draft",
        {"output": [{}, {}], "session": "s", "usage": two_replies.as_dict()},
    )

    [step] = _ledger(sqlite_engine, campaign_id).steps
    assert (step.input_tokens, step.output_tokens, step.total_tokens) == (0, 1400, 1400)
    # 1400 * 15 micro-dollars.
    assert step.cost_usd == pytest.approx(0.021)


def test_campaign_totals_add_up_over_its_steps(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine)
    # Four replies of 1000 in and 250 out, 6750 micro-dollars each, over three steps.
    for step, replies in (("strategist", 1), ("research", 1), ("writer", 2)):
        add_usage(
            sqlite_engine,
            campaign_id,
            step,
            cost_micros=6750 * replies,
            input_tokens=1000 * replies,
            output_tokens=250 * replies,
        )

    ledger = _ledger(sqlite_engine, campaign_id)

    assert {s.step for s in ledger.steps} == {"strategist", "research", "writer"}
    assert (ledger.input_tokens, ledger.output_tokens, ledger.total_tokens) == (4000, 1000, 5000)
    assert ledger.cost_usd == pytest.approx(0.027)


def test_totals_are_the_exact_sum_of_the_steps_for_any_ledger() -> None:
    rng = random.Random(SEED)

    for _ in range(CASES):
        rows = [
            db.StepUsage(
                step=f"s{i}",
                model=SCRIPTED_MODEL,
                input_tokens=rng.randint(0, 10**7),
                output_tokens=rng.randint(0, 10**7),
                cost_micros=rng.randint(0, 10**11),
                cache_hit=rng.random() < 0.3,
            )
            for i in range(rng.randint(0, 8))
        ]

        out = CostOut.of(rows)

        assert out.input_tokens == sum(s.input_tokens for s in out.steps)
        assert out.output_tokens == sum(s.output_tokens for s in out.steps)
        assert out.total_tokens == out.input_tokens + out.output_tokens
        assert cost.to_micros(out.cost_usd) == sum(r.cost_micros for r in rows)


def test_a_budget_raise_above_the_spend_is_kept(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine, budget_micros=10_000)
    add_usage(sqlite_engine, campaign_id, "first", cost_micros=1_000)

    change = set_budget(sqlite_engine, campaign_id, 30_000)

    assert change == BudgetChange()
    with Session(sqlite_engine) as session:
        assert session.get_one(db.Campaign, campaign_id).budget_micros == 30_000


def test_a_budget_raise_must_clear_what_was_spent(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine, budget_micros=10_000, status=db.BUDGET_PAUSED)
    add_usage(sqlite_engine, campaign_id, "first", cost_micros=21_000)

    # $0.021 is spent, so $0.02 (and exactly the spend) would pause again at once.
    too_low = set_budget(sqlite_engine, campaign_id, 20_000)
    equal = set_budget(sqlite_engine, campaign_id, 21_000)

    assert too_low == equal == BudgetChange(too_low_for=21_000)
    assert campaign_status(sqlite_engine, campaign_id) == db.BUDGET_PAUSED
    with Session(sqlite_engine) as session:
        assert session.get_one(db.Campaign, campaign_id).budget_micros == 10_000


def test_raising_the_budget_of_a_paused_run_sets_it_drafting_again(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine, budget_micros=10_000, status=db.BUDGET_PAUSED)
    add_usage(sqlite_engine, campaign_id, "first", cost_micros=21_000)

    change = set_budget(sqlite_engine, campaign_id, 1_000_000)

    assert change == BudgetChange(was_paused=True)
    assert campaign_status(sqlite_engine, campaign_id) == db.DRAFTING
    with Session(sqlite_engine) as session:
        events = db.events_after(sqlite_engine, campaign_id, 0)
        assert [(e.step, e.status) for e in events] == [(db.RUN_STEP, db.DRAFTING)]
        assert session.get_one(db.Campaign, campaign_id).budget_micros == 1_000_000


@pytest.mark.parametrize("budget", BAD_BUDGETS[:-1], ids=repr)
def test_a_campaign_budget_must_be_a_positive_amount_within_the_cap(budget: object) -> None:
    with pytest.raises(ValidationError):
        NewCampaign(report=REPORT, budget_usd=budget)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NewBudget(budget_usd=budget)  # type: ignore[arg-type]


def test_a_campaign_may_have_no_budget_or_one_up_to_the_cap() -> None:
    assert NewCampaign(report=REPORT).budget_usd is None
    assert NewCampaign(report=REPORT, budget_usd=0.01).budget_usd == 0.01
    assert NewBudget(budget_usd=MAX_BUDGET_USD).budget_usd == MAX_BUDGET_USD
