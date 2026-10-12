"""Seam 1 at fast depth: team isolation. Two teams share one Campaign API and one
Postgres; a team's token never reaches the other team's campaigns, runs, events, assets,
or previews. Row-level security is the only team filter: the API names the caller's team
on the database session and the database's policies do the filtering."""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from ace_engine import db, row_security
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME
from ace_engine.step_cache import CacheKey, StepCache, input_hash
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from tests.api.conftest import SignIn
from tests.api.helpers import AWAITING, create_on, until_status
from tests.harness.stack import Stack

ROOT = Path(__file__).resolve().parents[2]
TEAM_A, TEAM_B = "demand-gen", "product-marketing"
TEAM_B_OWNER = "pm-owner@demo.example"
TEAM_B_APPROVER = "pm-approver@demo.example"
# The database role the API's requests run as, and the setting that names their team.
TEAM_ROLE = "ace_team"
TEAM_SETTING = "ace.team"
# Workflows and platform alerts are shared by every team (docs/decisions/team-isolation.md).
SHARED_TABLES = {"workflow_versions", "alerts"}
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


@pytest.fixture
def team_a_campaign(api: httpx.Client) -> dict[str, Any]:
    """A team A campaign that ran its agent steps and waits for approval."""
    created = create_on(api, DEFAULT_WORKFLOW_NAME)
    return until_status(api, created["id"], AWAITING)


@pytest.fixture
def database(stack: Stack) -> Iterator[Engine]:
    engine = create_engine(stack.database_url)
    yield engine
    engine.dispose()


def _rows_seen_as(database: Engine, team: str, campaign_id: str) -> dict[str, int]:
    """How many rows of the campaign each team table shows to a request of `team`."""
    counts: dict[str, int] = {}
    with database.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL ROLE {TEAM_ROLE}"))
        conn.execute(
            text("SELECT set_config(:name, :team, true)"), {"name": TEAM_SETTING, "team": team}
        )
        counts["campaigns"] = conn.execute(
            text("SELECT count(*) FROM campaigns WHERE id = :id"), {"id": campaign_id}
        ).scalar_one()
        for table in ("run_events", "step_outputs", "step_usage", "campaign_traces"):
            counts[table] = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE campaign_id = :id"), {"id": campaign_id}
            ).scalar_one()
    return counts


def test_row_level_security_is_on_for_every_team_table(
    team_a_campaign: dict[str, Any], database: Engine
) -> None:
    team_tables = set(db.Base.metadata.tables) - SHARED_TABLES
    with database.connect() as conn:
        rows = conn.execute(
            text("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(:names)"),
            {"names": list(team_tables)},
        ).all()

    assert team_tables, "no team tables found"
    assert {name: is_on for name, is_on in rows} == dict.fromkeys(team_tables, True)


def test_the_team_role_sees_only_its_own_rows_without_a_team_condition(
    team_a_campaign: dict[str, Any], database: Engine
) -> None:
    own = _rows_seen_as(database, TEAM_A, team_a_campaign["id"])
    other = _rows_seen_as(database, TEAM_B, team_a_campaign["id"])
    nobody = _rows_seen_as(database, "", team_a_campaign["id"])

    assert all(own[t] > 0 for t in ("campaigns", "run_events", "step_outputs", "campaign_traces"))
    assert other == dict.fromkeys(own, 0)
    assert nobody == dict.fromkeys(own, 0)


def test_api_code_adds_no_team_condition() -> None:
    """The campaign queries name no team: row-level security is the only team filter."""
    team_condition = re.compile(
        r"\.team\s*(==|!=)|\bteam\s*=\s*:|Campaign\.team\b|StepCacheEntry\.team\b|[\"']team[\"']\s*:"
    )
    sources = [
        *(ROOT / "apps/api/campaign_api").glob("*.py"),
        ROOT / "apps/engine/ace_engine/db.py",
        ROOT / "apps/engine/ace_engine/step_cache.py",
    ]

    found = [
        f"{path.name}:{n}: {line.strip()}"
        for path in sources
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if team_condition.search(line)
    ]

    assert found == []


def test_install_quotes_every_identifier_in_its_ddl(database: Engine) -> None:
    """DDL cannot take bound parameters, so each table, policy, and role name in the
    installer's grants and policies is a quoted identifier."""
    executed: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        executed.append(statement)

    event.listen(database, "before_cursor_execute", record)
    try:
        row_security.install(database)
    finally:
        event.remove(database, "before_cursor_execute", record)

    ddl = [s for s in executed if s.startswith(("GRANT", "ALTER TABLE", "DROP POLICY", "CREATE"))]
    unquoted = [s for s in ddl if re.search(r"\b(ON|TO|TABLE|POLICY|SCHEMA|FROM)\s+[a-z_]", s)]
    assert ddl, "the installer ran no DDL"
    assert unquoted == []
    for table in row_security.team_tables():
        assert any(f'CREATE POLICY "{table}_by_team" ON "{table}"' in s for s in ddl)


def test_team_b_sees_none_of_team_a_campaigns_runs_or_assets(
    api: httpx.Client, sign_in: SignIn, team_a_campaign: dict[str, Any]
) -> None:
    team_b = sign_in(TEAM_B_OWNER)
    campaign_id = team_a_campaign["id"]

    listed = team_b.get("/campaigns")
    statuses = {path: team_b.get(path.format(id=campaign_id)).status_code for path in READ_PATHS}
    events_by_param = team_b.get(
        f"/campaigns/{campaign_id}/events",
        params={"access_token": team_b.headers["Authorization"].removeprefix("Bearer ")},
        headers={"Authorization": ""},
    )

    assert listed.status_code == 200
    assert campaign_id not in {c["id"] for c in listed.json()}
    assert statuses == dict.fromkeys(READ_PATHS, 404)
    assert events_by_param.status_code == 404
    # Team A still sees its own campaign, so the 404s are the team rule, not a lost row.
    assert api.get(f"/campaigns/{campaign_id}").status_code == 200
    assert campaign_id in {c["id"] for c in api.get("/campaigns").json()}


def test_team_b_cannot_act_on_team_a_campaigns(
    api: httpx.Client, sign_in: SignIn, team_a_campaign: dict[str, Any]
) -> None:
    campaign_id = team_a_campaign["id"]
    owner_b, approver_b = sign_in(TEAM_B_OWNER), sign_in(TEAM_B_APPROVER)

    approve = approver_b.post(f"/campaigns/{campaign_id}/approve")
    retry = owner_b.post(f"/campaigns/{campaign_id}/retry")
    budget = owner_b.post(f"/campaigns/{campaign_id}/budget", json={"budget_usd": 5})

    assert (approve.status_code, retry.status_code, budget.status_code) == (404, 404, 404)
    after = api.get(f"/campaigns/{campaign_id}").json()
    assert after["status"] == AWAITING
    assert after["budget_usd"] == team_a_campaign["budget_usd"]


def test_two_teams_run_campaigns_at_once_without_mixing_data(
    api: httpx.Client, sign_in: SignIn
) -> None:
    team_b = sign_in(TEAM_B_OWNER)
    report_a = f"Team A report {uuid.uuid4()}\nActors exploit unpatched VPN appliances."
    report_b = f"Team B report {uuid.uuid4()}\nActors phish payroll staff."

    a = create_on(api, DEFAULT_WORKFLOW_NAME, report_a)
    b = create_on(team_b, DEFAULT_WORKFLOW_NAME, report_b)
    done_a = until_status(api, a["id"], AWAITING)
    done_b = until_status(team_b, b["id"], AWAITING)

    assert (done_a["team"], done_b["team"]) == (TEAM_A, TEAM_B)
    assert (done_a["report"], done_b["report"]) == (report_a, report_b)
    seen_by_a = {c["id"] for c in api.get("/campaigns").json()}
    seen_by_b = {c["id"] for c in team_b.get("/campaigns").json()}
    assert a["id"] in seen_by_a and b["id"] not in seen_by_a
    assert b["id"] in seen_by_b and a["id"] not in seen_by_b
    assert {c["team"] for c in team_b.get("/campaigns").json()} == {TEAM_B}
    steps_a = api.get(f"/campaigns/{a['id']}/steps").json()
    steps_b = team_b.get(f"/campaigns/{b['id']}/steps").json()
    assert steps_a and steps_b
    assert {s["session"] for s in steps_a}.isdisjoint({s["session"] for s in steps_b})


def test_a_team_never_reads_another_teams_step_cache(database: Engine) -> None:
    """The step cache is a team table too: the database keeps one team's saved outputs from
    another, with no team condition in the cache's queries."""
    key = CacheKey("ace-email-writer", f"rev-{uuid.uuid4()}", input_hash("a report", {}, 0))
    StepCache(database, team=TEAM_A).put(key, {"ok": True}, model="m")

    own = StepCache(database, team=TEAM_A).get(key)
    other = StepCache(database, team=TEAM_B).get(key)

    assert own is not None and own.output == {"ok": True}
    assert other is None
