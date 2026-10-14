"""A campaign that opts in to the step cache reuses the saved result of an agent step it has
run before. The key is the step type, the agent revision digest and a hash of the input: a
re-run of an unchanged step is a hit that costs nothing in the ledger; a new agent revision
or a changed input misses. The worker's agent step runs against the scripted agent in-process;
the key's parts are unit-tested in test_step_cache.py."""

import asyncio
import uuid

import pytest
from ace_engine import cost, db, step_cache
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.exceptions import ApplicationError

from tests.support.dag import DRAFT_ONLY, REPORT
from tests.support.scripted_worker import ScriptedWorker, run_step, scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

STEP = "draft"
# The scripted agent bills 1000 tokens in and 500 out for each of the email writer's two replies.
SCRIPTED_TOKENS = (2000, 1000)
CARD_PATH = step_cache.CARD_PATH


class CachedRuns:
    """Campaigns of one team running `draft`, one scripted agent, one step cache."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.worker: ScriptedWorker = scripted_worker(engine)

    def run(self, report: str = REPORT, *, use_cache: bool = True) -> uuid.UUID:
        """A new campaign runs the step; its id."""
        campaign = seed_campaign(
            self.engine, CampaignSeed(dag=DRAFT_ONLY, status=db.DRAFTING, use_step_cache=use_cache)
        )
        run_step(self.worker, campaign, STEP, report)
        return campaign

    def usage(self, campaign: uuid.UUID) -> db.StepUsage:
        with Session(self.engine) as session:
            return session.get_one(db.StepUsage, (campaign, STEP))

    def agent_calls(self, campaign: uuid.UUID) -> list[str]:
        prefix = f"campaign-{campaign}:{STEP}"
        return [i for i, _ in self.worker.messages_sent() if i.startswith(prefix)]

    def card_reads(self) -> int:
        return len([r for r in self.worker.services.seen if r.url.path == CARD_PATH])

    def output(self, campaign: uuid.UUID) -> object:
        return {s.step: s.output for s in db.step_outputs(self.engine, campaign)}[STEP]


def _billed(usage: db.StepUsage) -> tuple[int, int]:
    return usage.input_tokens, usage.output_tokens


def test_a_first_run_is_a_miss_that_is_billed(sqlite_engine: Engine) -> None:
    runs = CachedRuns(sqlite_engine)

    first = runs.run()

    usage = runs.usage(first)
    assert (usage.cache_hit, _billed(usage)) == (False, SCRIPTED_TOKENS)
    assert usage.cost_micros > 0
    assert len(runs.agent_calls(first)) == 2


def test_a_rerun_of_an_unchanged_step_is_a_hit_that_costs_nothing(sqlite_engine: Engine) -> None:
    runs = CachedRuns(sqlite_engine)
    first = runs.run()

    second = runs.run()

    usage = runs.usage(second)
    assert (usage.cache_hit, _billed(usage), usage.cost_micros) == (True, (0, 0), 0)
    assert runs.agent_calls(second) == []
    assert runs.output(second) == runs.output(first)
    with Session(sqlite_engine) as session:
        assert (
            session.get_one(db.Campaign, second).draft == session.get_one(db.Campaign, first).draft
        )


def test_a_new_agent_revision_misses_and_the_old_revisions_entry_is_still_there(
    sqlite_engine: Engine,
) -> None:
    runs = CachedRuns(sqlite_engine)
    runs.run()

    runs.worker.agent.set_revision("2")
    after_change = runs.run()
    runs.worker.agent.set_revision("1")
    back_again = runs.run()

    assert runs.usage(after_change).cache_hit is False
    assert len(runs.agent_calls(after_change)) == 2
    assert runs.usage(back_again).cache_hit is True


def test_a_changed_report_misses_the_cache(sqlite_engine: Engine) -> None:
    runs = CachedRuns(sqlite_engine)
    runs.run()

    other = runs.run(f"{REPORT}\nand one more line")

    assert runs.usage(other).cache_hit is False


def test_a_campaign_without_the_opt_in_neither_reads_nor_writes_the_cache(
    sqlite_engine: Engine,
) -> None:
    runs = CachedRuns(sqlite_engine)
    plain_first = runs.run(use_cache=False)
    assert runs.card_reads() == 0

    opted_in = runs.run(use_cache=True)
    runs.run(use_cache=False)

    assert runs.usage(plain_first).cache_hit is False
    assert runs.usage(opted_in).cache_hit is False  # the plain run saved nothing to reuse
    assert runs.card_reads() == 1  # only the opted-in run read the agent's card


def _spend_the_budget(engine: Engine, campaign: uuid.UUID) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            db.StepUsage(
                campaign_id=campaign,
                step="earlier",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_micros=10_500,
            )
        )


def test_a_hit_runs_when_the_budget_is_spent_and_a_miss_stops(sqlite_engine: Engine) -> None:
    runs = CachedRuns(sqlite_engine)
    runs.run()
    ceiling = 10_000
    assert cost.is_budget_spent(ceiling, 10_500)

    def spent_campaign() -> uuid.UUID:
        campaign = seed_campaign(
            sqlite_engine,
            CampaignSeed(
                dag=DRAFT_ONLY, status=db.DRAFTING, use_step_cache=True, budget_micros=ceiling
            ),
        )
        _spend_the_budget(sqlite_engine, campaign)
        return campaign

    hit = spent_campaign()
    run_step(runs.worker, hit, STEP, REPORT)
    miss = spent_campaign()
    with pytest.raises(ApplicationError) as stopped:
        asyncio.run(
            runs.worker.activities.run_agent_step(str(miss), f"{REPORT}\nnot cached", STEP, {})
        )

    assert runs.usage(hit).cache_hit is True
    assert stopped.value.type == cost.BUDGET_SPENT
    assert stopped.value.non_retryable
