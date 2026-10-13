"""Seam 1 at fast depth: a start on a database an older install left. The API, the worker,
and the learnings MCP server each call `db.make_engine` at start; it adds every column and
index the models have and the database lacks, and keeps the rows that were there
(docs/decisions/additive-schema-at-start.md). The index, quoting, and race checks read or
drive the database directly: no route shows them."""

import contextlib
import json
import re
import threading
import uuid
from collections.abc import Iterator

import httpx
import pytest
from ace_engine import dag as graph
from ace_engine import db
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.docker_client import DockerClient

from tests.api.helpers import (
    DRAFT_ONLY,
    OWNER,
    REPORT,
    draft_cost,
    run_cached,
    save_workflow,
    workflow_name,
)
from tests.harness.api_client import api_client
from tests.harness.stack import POSTGRES_DATA_DIR, POSTGRES_IMAGE, Stack

TEAM_A = "demand-gen"
TEAM_B_OWNER = "pm-owner@demo.example"
OLD_REPORT = "An old install's report\nIt was here before the upgrade."
# A column an older install had that the models no longer do: the start leaves it.
LEGACY_COLUMN = "legacy_note"
LEGACY_VALUE = "kept"
MISSING_INDEX = "ix_step_slots_team"
# A whole model table the old database lacks, for the race: nothing references it.
MISSING_TABLE = "alerts"
# The step's own DDL; `CREATE TABLE` comes from `create_all` and is not held to the rule.
STEP_DDL = ("ALTER TABLE", "CREATE INDEX")
UNQUOTED = re.compile(r"\b(ON|TABLE|COLUMN|EXISTS)\s+[a-z_]|\(\s*[a-z_]")


def build_old_schema(url: str, missing_tables: tuple[str, ...] = ()) -> uuid.UUID:
    """The current models less every column that is nullable or has a server default, less
    `ix_step_slots_team` and `missing_tables`, plus a column the models do not have, with one
    Demand Gen campaign. Returns that campaign's id."""
    engine = create_engine(url)
    old_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            q = conn.dialect.identifier_preparer.quote_identifier
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            tables = [t for t in db.Base.metadata.sorted_tables if t.name not in missing_tables]
            db.Base.metadata.create_all(conn, tables=tables)
            for table in tables:
                for column in table.columns:
                    if column.nullable or column.server_default is not None:
                        conn.execute(
                            text(f"ALTER TABLE {q(table.name)} DROP COLUMN {q(column.name)}")
                        )
            conn.execute(text(f"DROP INDEX {q(MISSING_INDEX)}"))
            conn.execute(text(f"ALTER TABLE {q('campaigns')} ADD COLUMN {q(LEGACY_COLUMN)} text"))
            conn.execute(
                text(
                    "INSERT INTO campaigns (id, report, team, created_by, status, dag, created_at,"
                    " legacy_note) VALUES (:id, :report, :team, 'old-owner',"
                    " 'awaiting_approval', CAST(:dag AS json), now(), :legacy)"
                ),
                {
                    "id": old_id,
                    "report": OLD_REPORT,
                    "team": TEAM_A,
                    "dag": json.dumps(graph.default_dag()),
                    "legacy": LEGACY_VALUE,
                },
            )
    finally:
        engine.dispose()
    return old_id


@pytest.fixture(scope="module")
def volume() -> Iterator[str]:
    name = f"ace-schema-test-{uuid.uuid4().hex[:8]}"
    yield name
    with contextlib.suppress(Exception):
        DockerClient().client.volumes.get(name).remove(force=True)


@pytest.fixture(scope="module")
def old_campaign_id(volume: str) -> uuid.UUID:
    """A plain Postgres from the pinned image leaves the old schema on the volume."""
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg").with_volume_mapping(
        volume, POSTGRES_DATA_DIR, "rw"
    ) as postgres:
        return build_old_schema(postgres.get_connection_url())


@pytest.fixture(scope="module")
def stack(volume: str, old_campaign_id: uuid.UUID) -> Iterator[Stack]:
    running = Stack(data_volume=volume).start()
    yield running
    running.stop()


@pytest.fixture
def owner(stack: Stack) -> Iterator[httpx.Client]:
    stack.agent.script([])
    with api_client(stack.api_url, stack.dex.token(OWNER)) as client:
        yield client


@pytest.fixture
def database(stack: Stack) -> Iterator[Engine]:
    engine = create_engine(stack.database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def postgres() -> Iterator[PostgresContainer]:
    """A Postgres for the checks that call `make_engine` directly."""
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


def old_database(postgres: PostgresContainer, missing_tables: tuple[str, ...] = ()) -> str:
    """A new database in `postgres` with the old schema; returns its URL."""
    name = f"old_{uuid.uuid4().hex[:8]}"
    admin = create_engine(postgres.get_connection_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    url = postgres.get_connection_url().rsplit("/", 1)[0] + f"/{name}"
    build_old_schema(url, missing_tables)
    return url


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


def test_old_database_serves_a_new_campaign_with_its_budget(owner: httpx.Client) -> None:
    created = owner.post("/campaigns", json={"report": REPORT, "budget_usd": 5})

    assert created.status_code == 201, created.text
    assert created.json()["budget_usd"] == 5
    read = owner.get(f"/campaigns/{created.json()['id']}")
    assert read.status_code == 200, read.text
    assert read.json()["budget_usd"] == 5


def test_old_database_runs_the_step_cache(owner: httpx.Client) -> None:
    workflow = workflow_name("upgrade")
    save_workflow(owner, workflow, DRAFT_ONLY)
    report = f"{REPORT}\ncase {uuid.uuid4().hex}"

    first = run_cached(owner, workflow, report)
    second = run_cached(owner, workflow, report)

    assert draft_cost(first)["cache_hit"] is False
    assert draft_cost(second)["cache_hit"] is True


def test_old_campaign_is_kept_for_its_team_only(
    stack: Stack, owner: httpx.Client, old_campaign_id: uuid.UUID
) -> None:
    mine = owner.get(f"/campaigns/{old_campaign_id}")
    with api_client(stack.api_url, stack.dex.token(TEAM_B_OWNER)) as other_team:
        theirs = other_team.get(f"/campaigns/{old_campaign_id}")

    assert mine.status_code == 200, mine.text
    assert mine.json()["report"] == OLD_REPORT
    assert theirs.status_code == 404


def test_missing_model_index_exists_after_start(database: Engine) -> None:
    with database.connect() as conn:
        found = conn.scalar(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = :name"),
            {"name": MISSING_INDEX},
        )

    assert found == 1


def test_column_not_in_the_models_is_kept(database: Engine, old_campaign_id: uuid.UUID) -> None:
    with database.connect() as conn:
        kept = conn.scalar(
            text("SELECT legacy_note FROM campaigns WHERE id = :id"),
            {"id": old_campaign_id},
        )

    assert kept == LEGACY_VALUE


def test_second_start_on_the_upgraded_volume_lists_every_campaign(
    stack: Stack, volume: str, old_campaign_id: uuid.UUID
) -> None:
    """Runs last in the module: it stops the first stack."""
    with api_client(stack.api_url, stack.dex.token(OWNER)) as first:
        before = {c["id"] for c in first.get("/campaigns").json()}
    stack.stop()

    with (
        Stack(data_volume=volume) as again,
        api_client(again.api_url, again.dex.token(OWNER)) as owner,
    ):
        listed = owner.get("/campaigns")

    assert listed.status_code == 200, listed.text
    assert str(old_campaign_id) in before
    assert {c["id"] for c in listed.json()} == before


def test_second_make_engine_runs_no_ddl(postgres: PostgresContainer) -> None:
    url = old_database(postgres)
    db.make_engine(url).dispose()

    with recorded_sql() as executed:
        db.make_engine(url).dispose()

    assert [s for s in executed if s.startswith((*STEP_DDL, "CREATE TABLE"))] == []


def test_start_quotes_every_identifier_in_its_ddl(postgres: PostgresContainer) -> None:
    url = old_database(postgres)

    with recorded_sql() as executed:
        db.make_engine(url).dispose()

    ddl = [s for s in executed if s.startswith(STEP_DDL)]
    assert ddl, "the start ran no DDL"
    assert [s for s in ddl if UNQUOTED.search(s)] == []
    assert any('ALTER TABLE "campaigns" ADD COLUMN "budget_micros"' in s for s in ddl)
    assert any(
        f'CREATE INDEX IF NOT EXISTS "{MISSING_INDEX}" ON "step_slots" ("team")' in s for s in ddl
    )


def test_two_starts_at_once_on_an_old_database_both_succeed(postgres: PostgresContainer) -> None:
    url = old_database(postgres, missing_tables=(MISSING_TABLE,))
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

    assert errors == []
    engine = create_engine(url)
    try:
        assert MISSING_TABLE in inspect(engine).get_table_names()
        assert "budget_micros" in {c["name"] for c in inspect(engine).get_columns("campaigns")}
    finally:
        engine.dispose()


def test_sqlite_engine_still_builds_every_table() -> None:
    engine = db.make_engine("sqlite://")

    assert set(inspect(engine).get_table_names()) == set(db.Base.metadata.tables)
