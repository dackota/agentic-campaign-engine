"""Databases an older install left, to start the app's `db.make_engine` on: the current models
with columns and indexes taken away, on a database of the shared Postgres server."""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from ace_engine import dag as graph
from ace_engine import db
from sqlalchemy import create_engine, make_url, text
from testcontainers.community.postgres import PostgresContainer

TEAM_A = "demand-gen"
OLD_REPORT = "An old install's report\nIt was here before the upgrade."
# A column an older install had that the models no longer do: the start leaves it.
LEGACY_COLUMN = "legacy_note"
LEGACY_VALUE = "kept"
MISSING_INDEX = "ix_step_slots_team"
# A whole model table the old database lacks, for the race: nothing references it.
MISSING_TABLE = "alerts"
# A NOT NULL column with no server default (`created_by`) cannot be added to a table with
# rows; a nullable one (`budget_micros`) can.
UNADDABLE = "created_by"
ADDABLE = "budget_micros"


@contextmanager
def blank_database(server: PostgresContainer) -> Iterator[str]:
    """A new, empty database of `server`; its URL. Dropped on exit."""
    url = make_url(server.get_connection_url())
    name = f"old_{uuid.uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def build_old_schema(url: str, missing_tables: tuple[str, ...] = ()) -> uuid.UUID:
    """The current models less every column that is nullable or has a server default, less
    `MISSING_INDEX` and `missing_tables`, plus a column the models do not have, with one Demand
    Gen campaign. Returns that campaign's id."""
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
