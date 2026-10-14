"""The Campaign API in-process on a real Postgres engine, for the tests where row-level
security is the point: the same wiring as the `app_client` fixture, over the engine of
`postgres_engine`."""

from collections.abc import Iterator
from contextlib import contextmanager

from campaign_api.main import create_app
from campaign_api.trace_middleware import reset as reset_trace_cache
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.app import StubTemporal, StubVerifier
from tests.support.settings import unit_settings


@contextmanager
def api_over(engine: Engine, temporal: StubTemporal | None = None) -> Iterator[TestClient]:
    """A client of the real routes; a token is a demo user's email, as for `app_client`."""
    reset_trace_cache()
    app = create_app(
        unit_settings(),
        engine=engine,
        verifier=StubVerifier(),  # type: ignore[arg-type]
        temporal=temporal or StubTemporal(),  # type: ignore[arg-type]
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_trace_cache()
