"""Seam 1 at fast depth: Grafana's alert webhook feeds the in-app banner and, when Slack is
on, a Slack notice. The webhook needs the shared token; `GET /alerts` lists what is firing
for any signed-in user."""

import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.api.helpers import OWNER, POLL_INTERVAL_SECONDS, POLL_SECONDS
from tests.harness.stack import Stack

HTTP_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def wired() -> Iterator[Stack]:
    """A stack with Slack switched on, pointed at a local stand-in."""
    with Stack(integrations=True) as running:
        yield running


def alert(name: str, status: str = "firing", summary: str = "something broke") -> dict[str, Any]:
    return {
        "status": status,
        "labels": {"alertname": name},
        "annotations": {"summary": summary},
        "startsAt": "2026-10-11T10:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z" if status == "firing" else "2026-10-11T10:05:00Z",
        "fingerprint": f"fp-{name}",
    }


def send(stack: Stack, *alerts: dict[str, Any], token: str | None = None) -> httpx.Response:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return httpx.post(
        f"{stack.api_url}/alerts/webhook",
        json={"receiver": "ace-api", "alerts": list(alerts)},
        headers=headers,
        timeout=HTTP_TIMEOUT_SECONDS,
    )


def firing(stack: Stack, sign_in: Any) -> list[dict[str, Any]]:
    response = sign_in(OWNER).get("/alerts")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return rows


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def slack_texts(stack: Stack, name: str) -> list[str]:
    deadline = time.monotonic() + POLL_SECONDS
    texts: list[str] = []
    while time.monotonic() < deadline:
        messages = httpx.get(stack.slack_messages_url, timeout=HTTP_TIMEOUT_SECONDS).json()
        texts = [m["text"] for m in messages if name in m["text"]]
        if texts:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    return texts


def test_webhook_without_the_token_is_refused_and_records_nothing(
    stack: Stack, sign_in: Any
) -> None:
    name = unique("gateway-failover")

    assert send(stack, alert(name)).status_code == 401
    assert send(stack, alert(name), token="wrong-token").status_code == 401

    assert name not in [a["name"] for a in firing(stack, sign_in)]


def test_a_fired_alert_shows_in_the_banner_list(stack: Stack, sign_in: Any) -> None:
    name = unique("run-failure-rate")

    assert (
        send(
            stack, alert(name, summary="30% of runs failed"), token=stack.alert_webhook_token
        ).status_code
        == 202
    )

    [shown] = [a for a in firing(stack, sign_in) if a["name"] == name]
    assert shown["summary"] == "30% of runs failed"


def test_a_resolved_alert_leaves_the_banner_list(stack: Stack, sign_in: Any) -> None:
    name = unique("cost-spike")
    token = stack.alert_webhook_token
    assert send(stack, alert(name), token=token).status_code == 202

    assert send(stack, alert(name, status="resolved"), token=token).status_code == 202

    assert name not in [a["name"] for a in firing(stack, sign_in)]


def test_the_alert_list_needs_a_signed_in_user(stack: Stack) -> None:
    assert httpx.get(f"{stack.api_url}/alerts", timeout=HTTP_TIMEOUT_SECONDS).status_code == 401


def test_a_malformed_alert_body_is_refused(stack: Stack) -> None:
    response = httpx.post(
        f"{stack.api_url}/alerts/webhook",
        json={"alerts": [{"status": "firing"}]},
        headers={"Authorization": f"Bearer {stack.alert_webhook_token}"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    assert response.status_code == 422


def test_slack_gets_one_notice_per_firing_and_one_when_it_resolves(
    wired: Stack, sign_in: Any
) -> None:
    name = unique("eval-score-drop")
    token = wired.alert_webhook_token

    assert send(wired, alert(name, summary="score fell"), token=token).status_code == 202
    # Grafana repeats a firing alert; the repeat is not a new notice.
    assert send(wired, alert(name, summary="score fell"), token=token).status_code == 202
    first = slack_texts(wired, name)
    assert send(wired, alert(name, status="resolved"), token=token).status_code == 202
    deadline = time.monotonic() + POLL_SECONDS
    while len(slack_texts(wired, name)) < 2 and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
    texts = slack_texts(wired, name)

    assert len(first) == 1 and "score fell" in first[0]
    assert len(texts) == 2 and "resolved" in texts[1].lower()
    assert wired.slack_token not in str(texts)


def test_slack_off_still_records_the_alert(stack: Stack, sign_in: Any) -> None:
    assert stack.integrations is False
    name = unique("gateway-failover")

    assert send(stack, alert(name), token=stack.alert_webhook_token).status_code == 202

    assert name in [a["name"] for a in firing(stack, sign_in)]
