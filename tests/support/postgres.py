"""A real pgvector Postgres for the tests that need row-level security, pgvector or advisory
locks. One container serves a whole pytest session (an xdist worker); each test gets its own
database in it, with the schema applied by the app's own `db.make_engine` and
`row_security.install`."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from ace_engine import db, row_security
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer


@contextmanager
def fresh_database(server: PostgresContainer) -> Iterator[Engine]:
    """An engine on a new, empty database of `server` with the schema; dropped on exit."""
    url = make_url(server.get_connection_url())
    name = f"t_{uuid.uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = db.make_engine(url.set(database=name).render_as_string(hide_password=False))
    try:
        row_security.install(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
