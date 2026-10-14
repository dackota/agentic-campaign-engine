"""A start on a database an older install left. The API, the worker, and the learnings MCP
server each call `db.make_engine` at start; it adds every column and index the models have and
the database lacks, and keeps the rows that were there
(docs/decisions/additive-schema-at-start.md). The old install is a Postgres database with the
current models less their nullable columns and one index, plus a column the models no longer
have."""

import contextlib
import re
import threading
import uuid
from collections.abc import Iterator

import pytest
from ace_engine import db, row_security
from ace_engine.step_cache import CacheKey, StepCache, input_hash
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer

from tests.support.dag import REPORT
from tests.support.old_schema import (
    LEGACY_VALUE,
    MISSING_INDEX,
    MISSING_TABLE,
    OLD_REPORT,
    TEAM_A,
    blank_database,
    build_old_schema,
)
from tests.support.pg_app import api_over

OWNER = {"Authorization": "Bearer dg-owner@demo.example"}
TEAM_B_OWNER = {"Authorization": "Bearer pm-owner@demo.example"}
# The step's own DDL; `CREATE TABLE` comes from `create_all` and is not held to the rule.
STEP_DDL = ("ALTER TABLE", "CREATE INDEX")
UNQUOTED = re.compile(r"\b(ON|TABLE|COLUMN|EXISTS)\s+[a-z_]|\(\s*[a-z_]")
BUDGET_USD = 5


class Upgraded:
    """An old database after one start on it, and the campaign it held."""

    def __init__(self, engine: Engine, old_campaign_id: uuid.UUID) -> None:
        self.engine = engine
        self.old_campaign_id = old_campaign_id


@pytest.fixture(scope="module")
def upgraded(postgres_server: PostgresContainer) -> Iterator[Upgraded]:
    """What the API's start does to an old database: `make_engine`, then the row-level
    security rules."""
    with blank_database(postgres_server) as url:
        old_campaign_id = build_old_schema(url)
        engine = db.make_engine(url)
        row_security.install(engine)
        yield Upgraded(engine, old_campaign_id)
        engine.dispose()


@contextlib.contextmanager
def recorded_sql() -> Iterator[list[str]]:
    executed: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        executed.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield executed
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def test_old_database_serves_a_new_campaign_with_its_budget(upgraded: Upgraded) -> None:
    with api_over(upgraded.engine) as client:
        created = client.post(
            "/campaigns", json={"report": REPORT, "budget_usd": BUDGET_USD}, headers=OWNER
        )
        read = client.get(f"/campaigns/{created.json()['id']}", headers=OWNER)

    assert created.status_code == 201, created.text
    assert created.json()["budget_usd"] == BUDGET_USD
    assert read.status_code == 200, read.text
    assert read.json()["budget_usd"] == BUDGET_USD


def test_old_database_runs_the_step_cache(upgraded: Upgraded) -> None:
    key = CacheKey("ace-email-writer", f"rev-{uuid.uuid4()}", input_hash(REPORT, {}, 0))
    cache = StepCache(upgraded.engine, team=TEAM_A)

    assert cache.get(key) is None
    cache.put(key, {"ok": True}, model="m")

    hit = cache.get(key)
    assert hit is not None and hit.output == {"ok": True}


def test_old_campaign_is_kept_for_its_team_only(upgraded: Upgraded) -> None:
    with api_over(upgraded.engine) as client:
        mine = client.get(f"/campaigns/{upgraded.old_campaign_id}", headers=OWNER)
        theirs = client.get(f"/campaigns/{upgraded.old_campaign_id}", headers=TEAM_B_OWNER)

    assert mine.status_code == 200, mine.text
    assert mine.json()["report"] == OLD_REPORT
    assert theirs.status_code == 404


def test_missing_model_index_exists_after_start(upgraded: Upgraded) -> None:
    with upgraded.engine.connect() as conn:
        found = conn.scalar(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = :name"),
            {"name": MISSING_INDEX},
        )

    assert found == 1


def test_column_not_in_the_models_is_kept(upgraded: Upgraded) -> None:
    with upgraded.engine.connect() as conn:
        kept = conn.scalar(
            text("SELECT legacy_note FROM campaigns WHERE id = :id"),
            {"id": upgraded.old_campaign_id},
        )

    assert kept == LEGACY_VALUE


@pytest.fixture
def old_database_url(postgres_server: PostgresContainer) -> Iterator[str]:
    with blank_database(postgres_server) as url:
        build_old_schema(url)
        yield url


def test_second_make_engine_runs_no_ddl(old_database_url: str) -> None:
    db.make_engine(old_database_url).dispose()

    with recorded_sql() as executed:
        db.make_engine(old_database_url).dispose()

    assert [s for s in executed if s.startswith((*STEP_DDL, "CREATE TABLE"))] == []


def test_start_quotes_every_identifier_in_its_ddl(old_database_url: str) -> None:
    with recorded_sql() as executed:
        db.make_engine(old_database_url).dispose()

    ddl = [s for s in executed if s.startswith(STEP_DDL)]
    assert ddl, "the start ran no DDL"
    assert [s for s in ddl if UNQUOTED.search(s)] == []
    assert any('ALTER TABLE "campaigns" ADD COLUMN "budget_micros"' in s for s in ddl)
    assert any(
        f'CREATE INDEX IF NOT EXISTS "{MISSING_INDEX}" ON "step_slots" ("team")' in s for s in ddl
    )


def test_two_starts_at_once_on_an_old_database_both_succeed(
    postgres_server: PostgresContainer,
) -> None:
    with blank_database(postgres_server) as url:
        build_old_schema(url, missing_tables=(MISSING_TABLE,))
        together = threading.Barrier(2)
        errors: list[BaseException] = []

        def start() -> None:
            together.wait()
            try:
                db.make_engine(url).dispose()
            except BaseException as error:  # noqa: BLE001  the test reports every failure
                errors.append(error)

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        engine = create_engine(url)
        try:
            tables = inspect(engine).get_table_names()
            columns = {c["name"] for c in inspect(engine).get_columns("campaigns")}
        finally:
            engine.dispose()

    assert errors == []
    assert MISSING_TABLE in tables
    assert "budget_micros" in columns


def test_sqlite_engine_still_builds_every_table() -> None:
    engine = db.make_engine("sqlite://")

    assert set(inspect(engine).get_table_names()) == set(db.Base.metadata.tables)
