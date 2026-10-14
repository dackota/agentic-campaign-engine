"""Grafana's alert webhook feeds the in-app banner and, when Slack is on, a Slack notice. The
webhook needs the shared token; `GET /alerts` lists what is firing for any signed-in user. The
real routes run in process on SQLite (alerts are in no row-level-security table); Slack is the
fake over an ASGI transport."""

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from ace_engine.settings import Settings
from campaign_api import alerts
from campaign_api.alerts import AlertIn, AlertOut, AlertsIn
from campaign_api.main import create_app
from fake_slack.app import SlackConfig
from fake_slack.app import create_app as create_slack
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from tests.support.app import StubTemporal, StubVerifier
from tests.support.dag import OWNER
from tests.support.settings import unit_settings

ALERT_TOKEN = "alert-webhook-token"
SLACK_TOKEN = "xoxb-secret"
WEBHOOK = "/alerts/webhook"
SIGNED_IN = {"Authorization": f"Bearer {OWNER}"}
SENDER = {"Authorization": f"Bearer {ALERT_TOKEN}"}


@pytest.fixture
def app_settings() -> Settings:
    """Replaces the shared fixture: the webhook is on, and Slack is on with a stand-in."""
    return unit_settings(
        alert_webhook_token=ALERT_TOKEN,
        slack_token=SLACK_TOKEN,
        slack_channel="#alerts",
        slack_url="http://slack.test",
    )


@pytest.fixture
def slack(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The fake Slack. The route's own posts reach it through an ASGI transport."""
    fake = create_slack(SlackConfig(token=SLACK_TOKEN))
    real_post = alerts.post_to_slack

    async def post_via_fake(
        settings: Settings, text: str, client: httpx.AsyncClient | None = None
    ) -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fake)) as own:
            await real_post(settings, text, own)

    monkeypatch.setattr(alerts, "post_to_slack", post_via_fake)
    return TestClient(fake)


def alert(name: str, status: str = "firing", summary: str = "something broke") -> dict[str, Any]:
    return {
        "status": status,
        "labels": {"alertname": name},
        "annotations": {"summary": summary},
        "startsAt": "2026-10-11T10:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z" if status == "firing" else "2026-10-11T10:05:00Z",
        "fingerprint": f"fp-{name}",
    }


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def send(client: TestClient, *alert_bodies: dict[str, Any], sender: dict[str, str] = SENDER) -> int:
    response = client.post(
        WEBHOOK, json={"receiver": "ace-api", "alerts": list(alert_bodies)}, headers=sender
    )
    status: int = response.status_code
    return status


def banner(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/alerts", headers=SIGNED_IN)
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return rows


def slack_texts(slack: TestClient, name: str) -> list[str]:
    return [m["text"] for m in slack.get("/_messages").json() if name in m["text"]]


@pytest.mark.parametrize(
    "sender",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": f"Basic {ALERT_TOKEN}"}],
)
def test_webhook_without_the_token_is_refused_and_records_nothing(
    app_client: TestClient, sender: dict[str, str]
) -> None:
    name = unique("gateway-failover")

    assert send(app_client, alert(name), sender=sender) == 401

    assert banner(app_client) == []


def test_the_webhook_is_off_while_no_token_is_set(sqlite_engine: Engine) -> None:
    app = create_app(
        unit_settings(),
        engine=sqlite_engine,
        verifier=StubVerifier(),  # type: ignore[arg-type]
        temporal=StubTemporal(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        assert send(client, alert("x")) == 404


def test_a_fired_alert_shows_in_the_banner_list(app_client: TestClient) -> None:
    name = unique("run-failure-rate")

    assert send(app_client, alert(name, summary="30% of runs failed")) == 202

    [shown] = banner(app_client)
    assert (shown["name"], shown["summary"]) == (name, "30% of runs failed")


def test_a_resolved_alert_leaves_the_banner_list(app_client: TestClient) -> None:
    name = unique("cost-spike")
    assert send(app_client, alert(name)) == 202

    assert send(app_client, alert(name, status="resolved")) == 202

    assert banner(app_client) == []


def test_the_alert_list_needs_a_signed_in_user(app_client: TestClient) -> None:
    assert app_client.get("/alerts").status_code == 401
    assert app_client.get("/alerts", headers={"Authorization": "Bearer nobody"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"alerts": [{"status": "firing"}]},
        {"alerts": [{"status": "paused", "labels": {}, "fingerprint": "f"}]},
        {"alerts": [{"status": "firing", "labels": {"alertname": 7}, "fingerprint": "f"}]},
        {"alerts": [{"status": "firing", "labels": {}, "fingerprint": ""}]},
        {"alerts": "none"},
        {},
    ],
)
def test_a_malformed_alert_body_is_refused(app_client: TestClient, body: dict[str, Any]) -> None:
    response = app_client.post(WEBHOOK, json=body, headers=SENDER)

    assert response.status_code == 422
    with pytest.raises(ValidationError):
        AlertsIn.model_validate(body)
    assert banner(app_client) == []


def test_a_body_that_is_not_json_is_refused(app_client: TestClient) -> None:
    response = app_client.post(WEBHOOK, content=b"{not json", headers=SENDER)

    assert response.status_code == 422


def test_slack_gets_one_notice_per_firing_and_one_when_it_resolves(
    app_client: TestClient, slack: TestClient
) -> None:
    name = unique("eval-score-drop")

    assert send(app_client, alert(name, summary="score fell")) == 202
    # Grafana repeats a firing alert; the repeat is not a new notice.
    assert send(app_client, alert(name, summary="score fell")) == 202
    first = slack_texts(slack, name)
    assert send(app_client, alert(name, status="resolved")) == 202
    texts = slack_texts(slack, name)

    assert first == [f"ALERT firing: {name}: score fell"]
    assert texts == [*first, f"ALERT resolved: {name}"]
    assert SLACK_TOKEN not in str(slack.get("/_messages").json())


def test_an_alert_that_fires_again_after_it_resolved_is_a_new_notice(
    app_client: TestClient, slack: TestClient
) -> None:
    name = unique("cost-spike")

    for status in ("firing", "resolved", "firing"):
        assert send(app_client, alert(name, status=status)) == 202

    assert [t.split(":")[0:2] for t in slack_texts(slack, name)] == [
        ["ALERT firing", f" {name}"],
        ["ALERT resolved", f" {name}"],
        ["ALERT firing", f" {name}"],
    ]
    assert [a["name"] for a in banner(app_client)] == [name]


def test_slack_off_still_records_the_alert(sqlite_engine: Engine) -> None:
    settings = unit_settings(alert_webhook_token=ALERT_TOKEN)
    assert settings.slack_enabled is False
    name = unique("gateway-failover")
    notices = alerts.record(
        sqlite_engine,
        [AlertIn(status="firing", labels={"alertname": name}, annotations={}, fingerprint="fp")],
    )

    def no_call(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("slack is off: no call expected")

    async def post() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_call)) as client:
            for notice in notices:
                await alerts.post_to_slack(settings, notice.text, client)

    asyncio.run(post())

    assert len(notices) == 1
    assert [a.name for a in alerts.firing(sqlite_engine)] == [name]


def test_record_keeps_each_alert_once_by_fingerprint_and_answers_what_changed(
    sqlite_engine: Engine,
) -> None:
    def firing(name: str, summary: str = "s") -> AlertIn:
        return AlertIn(
            status="firing",
            labels={"alertname": name},
            annotations={"summary": summary},
            fingerprint=f"fp-{name}",
        )

    def resolved(name: str) -> AlertIn:
        return AlertIn(status="resolved", labels={"alertname": name}, fingerprint=f"fp-{name}")

    first = alerts.record(sqlite_engine, [firing("a", "disk full")])
    repeat = alerts.record(sqlite_engine, [firing("a", "disk fuller")])
    unknown_resolved = alerts.record(sqlite_engine, [resolved("never-fired")])
    done = alerts.record(sqlite_engine, [resolved("a")])
    again = alerts.record(sqlite_engine, [resolved("a")])
    refired = alerts.record(sqlite_engine, [firing("a", "disk full again")])

    assert [n.text for n in first] == ["ALERT firing: a: disk full"]
    assert repeat == []
    assert unknown_resolved == []
    assert [n.text for n in done] == ["ALERT resolved: a"]
    assert again == []
    assert [n.text for n in refired] == ["ALERT firing: a: disk full again"]
    shown = alerts.firing(sqlite_engine)
    assert [(a.name, a.summary) for a in shown] == [("a", "disk full again")]
    assert isinstance(shown[0], AlertOut)
