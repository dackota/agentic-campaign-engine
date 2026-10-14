"""Each team's step slots: a team at its limit waits while another team's steps still run, a
slot comes back on release or when its lease ends, and claims racing for the last slot never
take more than the limit."""

import threading
import uuid
from datetime import timedelta

from ace_engine import team_slots
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.team_seed import OTHER_TEAM, TEAM, add_campaign

LIMIT = 2
LEASE = timedelta(minutes=2)
EXPIRED = timedelta(seconds=-1)
RACERS = 12
ROUNDS = 5


def _claim(
    engine: Engine, campaign_id: uuid.UUID, key: str, lease: timedelta = LEASE, limit: int = LIMIT
) -> bool:
    with Session(engine) as session, session.begin():
        return team_slots.claim(session, campaign_id, key, limit, lease)


def _release(engine: Engine, key: str) -> None:
    with Session(engine) as session, session.begin():
        team_slots.release(session, key)


def test_a_team_at_its_step_limit_waits_while_another_team_runs(postgres_engine: Engine) -> None:
    team_a = [add_campaign(postgres_engine, team=TEAM) for _ in range(3)]
    team_b = add_campaign(postgres_engine, team=OTHER_TEAM)

    first, second, third = (_claim(postgres_engine, c, f"a{i}") for i, c in enumerate(team_a))
    other = _claim(postgres_engine, team_b, "b0")

    assert (first, second, third) == (True, True, False)
    assert other is True


def test_a_step_that_holds_a_slot_may_claim_it_again_at_the_limit(postgres_engine: Engine) -> None:
    team_a = [add_campaign(postgres_engine) for _ in range(3)]
    for i in range(LIMIT):
        assert _claim(postgres_engine, team_a[i], f"a{i}")

    assert _claim(postgres_engine, team_a[0], "a0") is True
    assert _claim(postgres_engine, team_a[2], "a2") is False


def test_a_released_slot_goes_to_the_next_step_of_the_team(postgres_engine: Engine) -> None:
    team_a = [add_campaign(postgres_engine) for _ in range(3)]
    for i in range(LIMIT):
        assert _claim(postgres_engine, team_a[i], f"a{i}")
    assert _claim(postgres_engine, team_a[2], "a2") is False

    _release(postgres_engine, "a0")

    assert _claim(postgres_engine, team_a[2], "a2") is True
    assert _claim(postgres_engine, team_a[2], "a2") is True


def test_releasing_a_slot_that_is_not_held_does_nothing(postgres_engine: Engine) -> None:
    campaign = add_campaign(postgres_engine)
    assert _claim(postgres_engine, campaign, "held")

    _release(postgres_engine, "never-claimed")

    assert _claim(postgres_engine, add_campaign(postgres_engine), "second") is True
    assert _claim(postgres_engine, add_campaign(postgres_engine), "third") is False


def test_a_slot_whose_lease_ended_is_free_for_the_next_claim(postgres_engine: Engine) -> None:
    team_a = [add_campaign(postgres_engine) for _ in range(3)]
    assert _claim(postgres_engine, team_a[0], "dead-worker", lease=EXPIRED)
    assert _claim(postgres_engine, team_a[1], "live")

    assert _claim(postgres_engine, team_a[2], "next") is True
    assert _claim(postgres_engine, team_a[0], "dead-worker-again") is False


def _race_for_slots(engine: Engine, racers: int) -> int:
    """How many of `racers` steps of one team, all claiming at the same instant, got a slot."""
    campaigns = [add_campaign(engine) for _ in range(racers)]
    start = threading.Barrier(racers)
    won: list[bool] = []

    def race(campaign_id: uuid.UUID) -> None:
        start.wait()
        won.append(_claim(engine, campaign_id, f"race-{campaign_id}"))

    threads = [threading.Thread(target=race, args=(c,)) for c in campaigns]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for campaign_id in campaigns:
        _release(engine, f"race-{campaign_id}")
    return sum(won)


def test_claims_racing_for_the_last_slots_never_take_more_than_the_limit(
    postgres_engine: Engine,
) -> None:
    taken = [_race_for_slots(postgres_engine, RACERS) for _ in range(ROUNDS)]

    assert taken == [LIMIT] * ROUNDS
