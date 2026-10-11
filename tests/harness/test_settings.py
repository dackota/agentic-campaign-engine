"""Worker settings: Marketo has its own timeout, and a missing Marketo URL or credential
fails at start."""

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from ace_engine.settings import Depth, Settings
from campaign_worker.activities import Activities

from tests.api.helpers import GOOD_DRAFT

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
        "marketo_client_id": "client",
        "marketo_client_secret": "client-secret",
        "marketo_webhook_secret": "webhook-secret",
        "agent_timeout_seconds": AGENT_TIMEOUT,
    }
    values.update(overrides)
    return Settings(**values)


def test_empty_marketo_url_fails_at_start() -> None:
    with pytest.raises(ValueError, match="marketo_url"):
        _settings(marketo_url="")


@pytest.mark.parametrize(
    "name", ["marketo_client_id", "marketo_client_secret", "marketo_webhook_secret"]
)
def test_missing_marketo_credential_fails_at_start(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        _settings(**{name: " "})


def test_secrets_stay_out_of_the_settings_repr() -> None:
    text = repr(_settings())

    assert "client-secret" not in text
    assert "webhook-secret" not in text


def test_marketo_call_uses_its_own_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Timeout] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(httpx.Timeout(**request.extensions["timeout"]))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t-1"})
        return httpx.Response(200, json={"result": [{"id": 1, "receiptId": "r-1"}]})

    real_client = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr("campaign_worker.activities.httpx.AsyncClient", client)
    # This test is about the timeout; where receipts are stored is tested through the API.
    monkeypatch.setattr("campaign_worker.activities.db.save_receipt", lambda *args: None)
    settings = _settings(marketo_timeout_seconds=MARKETO_TIMEOUT)

    activities = Activities(settings, engine=None)  # type: ignore[arg-type]
    receipt = asyncio.run(activities.send_email(str(uuid.uuid4()), [GOOD_DRAFT, GOOD_DRAFT]))

    assert receipt == "r-1"
    assert seen and all(t == httpx.Timeout(MARKETO_TIMEOUT) for t in seen)
