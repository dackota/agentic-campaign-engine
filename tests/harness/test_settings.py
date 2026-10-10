"""Worker settings: Marketo has its own timeout, and a missing Marketo URL fails at start."""

import asyncio
from typing import Any

import httpx
import pytest
from ace_engine.settings import Depth, Settings
from campaign_worker import activities
from campaign_worker.activities import Activities

AGENT_TIMEOUT = 31.0
MARKETO_TIMEOUT = 7.0


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "depth": Depth.FAST,
        "database_url": "postgresql://unused",
        "temporal_address": "localhost:7233",
        "temporal_namespace": "default",
        "agent_url": "http://agent",
        "marketo_url": "http://marketo",
        "agent_timeout_seconds": AGENT_TIMEOUT,
    }
    values.update(overrides)
    return Settings(**values)


def test_empty_marketo_url_fails_at_start() -> None:
    with pytest.raises(ValueError, match="marketo_url"):
        _settings(marketo_url="")


def test_marketo_call_uses_its_own_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Timeout] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(httpx.Timeout(**request.extensions["timeout"]))
        return httpx.Response(200, json={"result": [{"receiptId": "r-1"}]})

    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(activities.httpx, "AsyncClient", client)
    settings = _settings(marketo_timeout_seconds=MARKETO_TIMEOUT)

    receipt = asyncio.run(Activities(settings, engine=None).send_email("c-1", {}))  # type: ignore[arg-type]

    assert receipt == "r-1"
    assert seen == [httpx.Timeout(MARKETO_TIMEOUT)]
