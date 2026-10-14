"""A start on a database that lacks a column it cannot add. A NOT NULL column with no server
default cannot be added to a table with rows, so the start fails, names `table.column`, and
leaves the database as it was (docs/decisions/additive-schema-at-start.md)."""

from collections.abc import Iterator

import pytest
from ace_engine import db
from sqlalchemy import create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from tests.support.old_schema import (
    ADDABLE,
    UNADDABLE,
    blank_database,
    build_schema_lacking_created_by,
)


@pytest.fixture
def blocked_database(postgres_server: PostgresContainer) -> Iterator[str]:
    """A database whose one campaign row blocks `created_by`."""
    with blank_database(postgres_server) as url:
        build_schema_lacking_created_by(url, with_row=True)
        yield url


def test_start_on_a_table_with_rows_names_the_column_it_cannot_add(blocked_database: str) -> None:
    with pytest.raises(RuntimeError) as raised:
        db.make_engine(blocked_database)

    assert f"campaigns.{UNADDABLE}" in str(raised.value)
    assert "server default or SQL of its own" in str(raised.value)


def test_failed_start_leaves_the_database_as_it_was(blocked_database: str) -> None:
    with pytest.raises(RuntimeError):
        db.make_engine(blocked_database)

    engine = create_engine(blocked_database)
    try:
        with engine.connect() as conn:
            rows = conn.scalar(text("SELECT count(*) FROM campaigns"))
        columns = {c["name"] for c in inspect(engine).get_columns("campaigns")}
    finally:
        engine.dispose()

    assert rows == 1
    assert ADDABLE not in columns


def test_not_null_column_is_added_to_an_empty_table(postgres_server: PostgresContainer) -> None:
    with blank_database(postgres_server) as url:
        build_schema_lacking_created_by(url, with_row=False)

        db.make_engine(url).dispose()

        engine = create_engine(url)
        try:
            columns = {c["name"] for c in inspect(engine).get_columns("campaigns")}
        finally:
            engine.dispose()

    assert {UNADDABLE, ADDABLE} <= columns
