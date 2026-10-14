"""Fixtures any test can ask for. Heavy imports (Docker, Temporal) stay inside the fixtures
that need them, so a unit test collects without them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from ace_engine import db
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from tests.support.app import StubTemporal, StubVerifier
from tests.support.settings import unit_settings

if TYPE_CHECKING:
    from ace_engine.settings import Settings
    from fastapi.testclient import TestClient
    from testcontainers.community.postgres import PostgresContainer


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """An in-memory SQLite database with every table. No row-level security, pgvector or
    advisory locks: a test that needs those asks for `postgres_engine`."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    db.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[PostgresContainer]:
    """One pinned pgvector Postgres for the session (one per xdist worker)."""
    from tests.harness.stack import owner_labels, postgres_container

    with postgres_container(owner_labels()) as server:
        yield server


@pytest.fixture
def postgres_engine(postgres_server: PostgresContainer) -> Iterator[Engine]:
    """An engine on a fresh database of the shared server, with the schema and the team
    row-level security rules applied. Dropped after the test."""
    from tests.support.postgres import fresh_database

    with fresh_database(postgres_server) as engine:
        yield engine


@pytest.fixture
def temporal() -> StubTemporal:
    return StubTemporal()


@pytest.fixture
def app_settings() -> Settings:
    return unit_settings()


@pytest.fixture
def app_client(
    app_settings: Settings, sqlite_engine: Engine, temporal: StubTemporal
) -> Iterator[TestClient]:
    """The real Campaign API in-process on SQLite. A token is a demo user's email
    (`Authorization: Bearer dg-owner@demo.example`); Temporal is `temporal`, a recorder."""
    from campaign_api.main import create_app
    from campaign_api.trace_middleware import reset as reset_trace_cache
    from fastapi.testclient import TestClient

    reset_trace_cache()
    app = create_app(
        app_settings,
        engine=sqlite_engine,
        verifier=StubVerifier(),  # type: ignore[arg-type]
        temporal=temporal,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        yield client
    reset_trace_cache()
