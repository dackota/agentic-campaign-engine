"""The shared fixtures in tests/conftest.py and tests/support/ do what their docstrings say."""

import threading
import uuid

from ace_engine import db
from campaign_api import trace_middleware
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from tests.support.app import StubTemporal
from tests.support.postgres import fresh_database
from tests.support.telemetry import install_metric_reader, install_span_exporter

OWNER = {"Authorization": "Bearer dg-owner@demo.example"}


def count_campaigns(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(db.Campaign)) or 0


def add_campaign(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(db.Campaign(report="r", team="t", created_by="u", dag={}))


def test_sqlite_engine_starts_empty_with_the_schema_and_serves_other_threads(
    sqlite_engine: Engine,
) -> None:
    assert count_campaigns(sqlite_engine) == 0
    add_campaign(sqlite_engine)
    seen: list[int] = []

    worker = threading.Thread(target=lambda: seen.append(count_campaigns(sqlite_engine)))
    worker.start()
    worker.join()

    assert seen == [1]


def test_postgres_engine_has_the_schema_pgvector_and_row_security(
    postgres_engine: Engine,
) -> None:
    add_campaign(postgres_engine)

    with postgres_engine.connect() as conn:
        has_vector = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        is_secured = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname='campaigns'")
        )
        assert has_vector.first() is not None
        assert is_secured.scalar_one() is True
    assert count_campaigns(postgres_engine) == 1


def test_each_fresh_database_is_empty(postgres_server: PostgresContainer) -> None:
    with fresh_database(postgres_server) as first:
        add_campaign(first)
        assert count_campaigns(first) == 1

    with fresh_database(postgres_server) as second:
        assert count_campaigns(second) == 0


def test_app_client_answers_healthz_without_a_token(app_client: TestClient) -> None:
    assert app_client.get("/healthz").status_code == 200


def test_app_client_refuses_a_missing_or_unknown_token(app_client: TestClient) -> None:
    assert app_client.get("/campaigns").status_code == 401
    assert (
        app_client.get("/campaigns", headers={"Authorization": "Bearer nobody"}).status_code == 401
    )


def test_app_client_signs_in_a_demo_user_and_stubs_temporal(
    app_client: TestClient, temporal: StubTemporal
) -> None:
    assert app_client.get("/me", headers=OWNER).json()["email"] == "dg-owner@demo.example"

    created = app_client.post("/campaigns", json={"report": "a report"}, headers=OWNER)

    assert created.status_code == 201, created.text
    assert [s["id"] for s in temporal.started] == [f"campaign-{created.json()['id']}"]
    assert app_client.get("/campaigns", headers=OWNER).json()[0]["id"] == created.json()["id"]


def test_the_trace_cache_is_forgotten_by_reset() -> None:
    campaign = uuid.uuid4()
    trace_middleware.remember(campaign, "team", "00-trace-span-01")

    trace_middleware.reset()

    assert (campaign, "team") not in trace_middleware._cached


def test_the_telemetry_helpers_record_spans_and_metrics() -> None:
    exporter = install_span_exporter()
    reader = install_metric_reader()

    with trace.get_tracer("fixtures-test").start_as_current_span("a-span"):
        metrics.get_meter("fixtures-test").create_counter("fixtures_total").add(3)

    assert "a-span" in [span.name for span in exporter.get_finished_spans()]
    data = reader.get_metrics_data()
    assert data is not None
    names = [m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics]
    assert "fixtures_total" in names
