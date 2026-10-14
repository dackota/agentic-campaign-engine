"""Team isolation, in the database and through the real Campaign API in process. Two teams
share one Postgres; a team's token never reaches the other team's campaigns, runs, events,
assets, or previews. Row-level security is the only team filter: the API names the caller's
team on the database session and the database's policies do the filtering."""

import uuid
from collections.abc import Iterator

import pytest
from ace_engine import db, learnings
from ace_engine.agent_roles import ROLES, message_for
from ace_engine.step_cache import CacheKey, StepCache, input_hash
from fastapi.testclient import TestClient
from sqlalchemy import column, func, select, text
from sqlalchemy import table as sql_table
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.harness.scripted_agent import default_reply
from tests.support.app import StubTemporal
from tests.support.dag import APPROVER, GOOD_DRAFT, REPORT
from tests.support.pg_app import api_over
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import CampaignSeed, seed_campaign
from tests.support.team_seed import OTHER_TEAM, TEAM, add_campaign

TEAM_A_OWNER = {"Authorization": "Bearer dg-owner@demo.example"}
TEAM_A_APPROVER = {"Authorization": f"Bearer {APPROVER}"}
TEAM_B_OWNER = {"Authorization": "Bearer pm-owner@demo.example"}
TEAM_B_APPROVER = {"Authorization": "Bearer pm-approver@demo.example"}
TEAM_B_TOKEN = "pm-owner@demo.example"
# The database role the API's requests run as, and the setting that names their team.
TEAM_ROLE = "ace_team"
TEAM_SETTING = "ace.team"
# Workflows and platform alerts are shared by every team (docs/decisions/team-isolation.md).
SHARED_TABLES = {"workflow_versions", "alerts"}
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TEAM_TABLES_WITH_ROWS = ("campaigns", "run_events", "step_outputs", "step_usage", "campaign_traces")
# Every per-campaign view a signed-in reader can open.
READ_PATHS = (
    "/campaigns/{id}",
    "/campaigns/{id}/events",
    "/campaigns/{id}/steps",
    "/campaigns/{id}/activity",
    "/campaigns/{id}/preview",
    "/campaigns/{id}/preview/one-pager",
    "/campaigns/{id}/preview/deck",
    "/campaigns/{id}/preview/landing-page",
    "/campaigns/{id}/preview/graphic",
)
NOT_FOUND = 404


def _seed_run(engine: Engine, team: str = TEAM) -> uuid.UUID:
    """A campaign of `team` that ran its writers and waits for approval: a draft, run events,
    outputs, a cost row and a trace."""
    campaign_id = add_campaign(engine, team=team, draft=GOOD_DRAFT)
    with Session(engine) as session, session.begin():
        db.add_event(session, campaign_id, "landing_page", db.STEP_SUCCEEDED)
        db.add_event(session, campaign_id, db.RUN_STEP, db.AWAITING_APPROVAL)
        for step in ("landing_page", "one_pager"):
            output = default_reply(message_for(ROLES[step], REPORT, {}))
            session.add(
                db.StepOutput(campaign_id=campaign_id, step=step, session=step, output=output)
            )
        session.add(
            db.StepUsage(
                campaign_id=campaign_id,
                step="landing_page",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_micros=1,
            )
        )
        session.add(db.CampaignTrace(campaign_id=campaign_id, traceparent=TRACEPARENT))
    return campaign_id


def _rows_seen_as(engine: Engine, team: str, campaign_id: uuid.UUID) -> dict[str, int]:
    """How many rows of the campaign each team table shows to a request of `team`."""
    counts: dict[str, int] = {}
    with engine.connect() as conn, conn.begin():
        role = conn.dialect.identifier_preparer.quote_identifier(TEAM_ROLE)
        conn.execute(text("SET LOCAL ROLE " + role))
        conn.execute(
            text("SELECT set_config(:name, :team, true)"), {"name": TEAM_SETTING, "team": team}
        )
        counts["campaigns"] = conn.execute(
            text("SELECT count(*) FROM campaigns WHERE id = :id"), {"id": campaign_id}
        ).scalar_one()
        for name in TEAM_TABLES_WITH_ROWS[1:]:
            counted = (
                select(func.count())
                .select_from(sql_table(name, column("campaign_id")))
                .where(column("campaign_id") == campaign_id)
            )
            counts[name] = conn.execute(counted).scalar_one()
    return counts


def test_row_level_security_is_on_for_every_team_table_and_off_for_the_shared_ones(
    postgres_engine: Engine,
) -> None:
    team_tables = set(db.Base.metadata.tables) - SHARED_TABLES
    with postgres_engine.connect() as conn:
        found = conn.execute(
            text("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(:names)"),
            {"names": [*team_tables, *SHARED_TABLES]},
        )
        rows: dict[str, bool] = {name: is_on for name, is_on in found}

    assert team_tables, "no team tables found"
    assert rows == {**dict.fromkeys(team_tables, True), **dict.fromkeys(SHARED_TABLES, False)}


def test_the_team_role_sees_only_its_own_rows_without_a_team_condition(
    postgres_engine: Engine,
) -> None:
    campaign_id = _seed_run(postgres_engine)

    own = _rows_seen_as(postgres_engine, TEAM, campaign_id)
    other = _rows_seen_as(postgres_engine, OTHER_TEAM, campaign_id)
    nobody = _rows_seen_as(postgres_engine, "", campaign_id)

    assert all(own[t] > 0 for t in TEAM_TABLES_WITH_ROWS)
    assert other == dict.fromkeys(own, 0)
    assert nobody == dict.fromkeys(own, 0)


@pytest.fixture
def temporal() -> StubTemporal:
    return StubTemporal()


@pytest.fixture
def client(postgres_engine: Engine, temporal: StubTemporal) -> Iterator[TestClient]:
    with api_over(postgres_engine, temporal) as running:
        yield running


def test_team_b_sees_none_of_team_a_campaigns_runs_or_assets(
    client: TestClient, postgres_engine: Engine
) -> None:
    campaign_id = _seed_run(postgres_engine)

    listed = client.get("/campaigns", headers=TEAM_B_OWNER)
    statuses = {
        path: client.get(path.format(id=campaign_id), headers=TEAM_B_OWNER).status_code
        for path in READ_PATHS
    }
    events_by_param = client.get(
        f"/campaigns/{campaign_id}/events", params={"access_token": TEAM_B_TOKEN}
    )

    assert listed.status_code == 200
    assert str(campaign_id) not in {c["id"] for c in listed.json()}
    assert statuses == dict.fromkeys(READ_PATHS, NOT_FOUND)
    assert events_by_param.status_code == NOT_FOUND


def test_team_a_still_sees_its_own_campaign_so_the_404s_are_the_team_rule(
    client: TestClient, postgres_engine: Engine
) -> None:
    campaign_id = _seed_run(postgres_engine)

    statuses = {
        path: client.get(path.format(id=campaign_id), headers=TEAM_A_OWNER).status_code
        for path in READ_PATHS
    }
    listed = client.get("/campaigns", headers=TEAM_A_OWNER)

    assert statuses == dict.fromkeys(READ_PATHS, 200)
    assert str(campaign_id) in {c["id"] for c in listed.json()}


def test_team_b_cannot_act_on_team_a_campaigns(client: TestClient, postgres_engine: Engine) -> None:
    campaign_id = _seed_run(postgres_engine)
    before = client.get(f"/campaigns/{campaign_id}", headers=TEAM_A_OWNER).json()

    approve = client.post(f"/campaigns/{campaign_id}/approve", headers=TEAM_B_APPROVER)
    retry = client.post(f"/campaigns/{campaign_id}/retry", headers=TEAM_B_OWNER)
    budget = client.post(
        f"/campaigns/{campaign_id}/budget", json={"budget_usd": 5}, headers=TEAM_B_OWNER
    )

    assert (approve.status_code, retry.status_code, budget.status_code) == (NOT_FOUND,) * 3
    after = client.get(f"/campaigns/{campaign_id}", headers=TEAM_A_OWNER).json()
    assert after == before


def test_a_team_never_reads_another_teams_step_cache(postgres_engine: Engine) -> None:
    """The step cache is a team table too: the database keeps one team's saved outputs from
    another, with no team condition in the cache's queries."""
    key = CacheKey("ace-email-writer", f"rev-{uuid.uuid4()}", input_hash("a report", {}, 0))
    StepCache(postgres_engine, team=TEAM).put(key, {"ok": True}, model="m")

    own = StepCache(postgres_engine, team=TEAM).get(key)
    other = StepCache(postgres_engine, team=OTHER_TEAM).get(key)

    assert own is not None and own.output == {"ok": True}
    assert other is None


# The approval inbox and the learnings: the routes build their team's view of the database, so
# a route that held the raw engine instead would show or change the other team's rows.

ASSET_STEPS = ("landing_page", "social", "one_pager", "email_writer", "design")
ASSET_ROUTES = ("approve", "reject")


def _seed_inbox_campaign(engine: Engine) -> uuid.UUID:
    """A team A campaign that waits for approval with every asset written."""
    outputs = {step: scripted_output(step) for step in ASSET_STEPS}
    return seed_campaign(engine, CampaignSeed(outputs=outputs))


def _decision_state(engine: Engine, campaign_id: uuid.UUID) -> dict[str, object]:
    """The campaign's status and how many approvals and events it holds, read as the owner."""
    with engine.connect() as conn:
        params = {"id": campaign_id}
        return {
            "status": conn.execute(
                text("SELECT status FROM campaigns WHERE id = :id"), params
            ).scalar_one(),
            "approvals": conn.execute(
                text("SELECT count(*) FROM asset_approvals WHERE campaign_id = :id"), params
            ).scalar_one(),
            "events": conn.execute(
                text("SELECT count(*) FROM run_events WHERE campaign_id = :id"), params
            ).scalar_one(),
        }


def test_team_b_sees_none_of_team_a_assets_in_the_inbox_and_team_a_still_does(
    client: TestClient, postgres_engine: Engine
) -> None:
    campaign_id = _seed_inbox_campaign(postgres_engine)

    team_b = client.get("/inbox", headers=TEAM_B_APPROVER)
    team_a = client.get("/inbox", headers=TEAM_A_APPROVER)

    assert team_b.status_code == 200
    assert team_b.json() == []
    assert {i["step"] for i in team_a.json() if i["campaign_id"] == str(campaign_id)} == set(
        ASSET_STEPS
    )


@pytest.mark.parametrize("route", ASSET_ROUTES)
def test_team_b_cannot_decide_team_a_assets_and_nothing_changes(
    client: TestClient, postgres_engine: Engine, temporal: StubTemporal, route: str
) -> None:
    campaign_id = _seed_inbox_campaign(postgres_engine)
    before = _decision_state(postgres_engine, campaign_id)

    refused = client.post(
        f"/campaigns/{campaign_id}/assets/social/{route}",
        json={"comment": "not yours"},
        headers=TEAM_B_APPROVER,
    )
    still_there = client.get("/inbox", headers=TEAM_A_APPROVER)

    assert refused.status_code == NOT_FOUND
    assert _decision_state(postgres_engine, campaign_id) == before
    assert temporal.signals == []
    assert {i["step"] for i in still_there.json()} == set(ASSET_STEPS)


@pytest.mark.parametrize("route", ASSET_ROUTES)
def test_team_a_approver_still_decides_its_own_assets_so_the_404s_are_the_team_rule(
    client: TestClient, postgres_engine: Engine, route: str
) -> None:
    campaign_id = _seed_inbox_campaign(postgres_engine)
    before = _decision_state(postgres_engine, campaign_id)

    decided = client.post(
        f"/campaigns/{campaign_id}/assets/social/{route}",
        json={"comment": "ok"},
        headers=TEAM_A_APPROVER,
    )

    assert decided.status_code == 200
    assert _decision_state(postgres_engine, campaign_id) != before


def _seed_learning(engine: Engine) -> uuid.UUID:
    """A learning of team A, from a campaign whose A/B test a winner was called on."""
    campaign_id = add_campaign(
        engine, draft=GOOD_DRAFT, variant_b={**GOOD_DRAFT, "subject": "Another subject"}
    )
    winner = learnings.Winner("A", 0.97, {"A": {"opens": 80}, "B": {"opens": 30}})
    assert learnings.learn_from_winner(engine, campaign_id, winner, learnings.stand_in_embedding)
    return campaign_id


def _learning_rows(engine: Engine) -> list[tuple[uuid.UUID, object]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT campaign_id, deleted_at FROM learnings")).all()
    return [(campaign_id, deleted_at) for campaign_id, deleted_at in rows]


def test_team_b_neither_reads_nor_deletes_team_a_learnings_and_team_a_does(
    client: TestClient, postgres_engine: Engine
) -> None:
    campaign_id = _seed_learning(postgres_engine)
    [mine] = client.get("/learnings", headers=TEAM_A_OWNER).json()
    path = f"/learnings/{mine['id']}"

    listed_by_b = client.get("/learnings", headers=TEAM_B_OWNER)
    deleted_by_b = client.delete(path, headers=TEAM_B_APPROVER)

    assert mine["campaign_id"] == str(campaign_id)
    assert (listed_by_b.status_code, listed_by_b.json()) == (200, [])
    assert deleted_by_b.status_code == NOT_FOUND
    assert _learning_rows(postgres_engine) == [(campaign_id, None)]
    assert client.delete(path, headers=TEAM_A_APPROVER).status_code == 200
    assert client.get("/learnings", headers=TEAM_A_OWNER).json() == []
