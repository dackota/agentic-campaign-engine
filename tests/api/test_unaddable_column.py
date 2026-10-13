"""Seam 1 at fast depth: a start on a database that lacks a column it cannot add. A NOT NULL
column with no server default cannot be added to a table with rows, so the API's start fails,
names `table.column`, and leaves the database as it was
(docs/decisions/additive-schema-at-start.md). No route answers once the start has failed, so
the checks read the database directly."""

import contextlib
import json
import uuid
from collections.abc import Iterator

import pytest
from ace_engine import dag as graph
from ace_engine import db
from sqlalchemy import create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.docker_client import DockerClient

from tests.harness.stack import POSTGRES_DATA_DIR, POSTGRES_IMAGE, Stack

UNADDABLE = "created_by"  # NOT NULL, no server default
ADDABLE = "budget_micros"  # nullable


def build_schema_lacking_created_by(url: str, *, with_row: bool) -> None:
    """The current models less `campaigns.created_by` and `campaigns.budget_micros`, with one
    Demand Gen campaign when `with_row`."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            q = conn.dialect.identifier_preparer.quote_identifier
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.Base.metadata.create_all(conn)
            for column in (UNADDABLE, ADDABLE):
                conn.execute(text(f"ALTER TABLE {q('campaigns')} DROP COLUMN {q(column)}"))
            if with_row:
                conn.execute(
                    text(
                        "INSERT INTO campaigns (id, report, team, status, dag, created_at)"
                        " VALUES (:id, 'An old report', 'demand-gen', 'awaiting_approval',"
                        " CAST(:dag AS json), now())"
                    ),
                    {"id": uuid.uuid4(), "dag": json.dumps(graph.default_dag())},
                )
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def volume() -> Iterator[str]:
    name = f"ace-unaddable-test-{uuid.uuid4().hex[:8]}"
    yield name
    with contextlib.suppress(Exception):
        DockerClient().client.volumes.get(name).remove(force=True)


@pytest.fixture(scope="module")
def failed_start(volume: str) -> str:
    """The error of a fast stack started over a volume whose one campaign row blocks
    `created_by`."""
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg").with_volume_mapping(
        volume, POSTGRES_DATA_DIR, "rw"
    ) as postgres:
        build_schema_lacking_created_by(postgres.get_connection_url(), with_row=True)
    with pytest.raises(RuntimeError) as raised:
        Stack(data_volume=volume).start()
    return str(raised.value)


def test_start_on_a_table_with_rows_names_the_column_it_cannot_add(failed_start: str) -> None:
    assert f"campaigns.{UNADDABLE}" in failed_start
    assert "server default or SQL of its own" in failed_start


def test_failed_start_leaves_the_database_as_it_was(volume: str, failed_start: str) -> None:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg").with_volume_mapping(
        volume, POSTGRES_DATA_DIR, "rw"
    ) as postgres:
        engine = create_engine(postgres.get_connection_url())
        try:
            with engine.connect() as conn:
                rows = conn.scalar(text("SELECT count(*) FROM campaigns"))
                added = conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns"
                        " WHERE table_name = 'campaigns' AND column_name = :column"
                    ),
                    {"column": ADDABLE},
                )
        finally:
            engine.dispose()

    assert rows == 1
    assert added == 0


def test_not_null_column_is_added_to_an_empty_table() -> None:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        build_schema_lacking_created_by(url, with_row=False)

        db.make_engine(url).dispose()

        engine = create_engine(url)
        try:
            columns = {c["name"] for c in inspect(engine).get_columns("campaigns")}
        finally:
            engine.dispose()

    assert {UNADDABLE, ADDABLE} <= columns
