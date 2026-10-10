"""Helpers the Campaign API tests share: make a campaign, wait for it to reach a status."""

import json
import time
from typing import Any

import httpx

REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."
GOOD_DRAFT = {
    "subject": "Patch your VPN today",
    "preheader": "Attackers are scanning for it",
    "body": "Hello, apply the fix now.",
    "call_to_action": "Patch now",
}
AWAITING = "awaiting_approval"
FAILED = "failed"
SENT = "sent"
# Demo users from platform/dex/config.yaml.
OWNER = "dg-owner@demo.example"
APPROVER = "dg-approver@demo.example"
POLL_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.2


def create(api: httpx.Client, report: str = REPORT) -> dict[str, Any]:
    response = api.post("/campaigns", json={"report": report})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def until_status(api: httpx.Client, campaign_id: str, *wanted: str) -> dict[str, Any]:
    """Poll the campaign until its status is one of `wanted`; return it."""
    deadline = time.monotonic() + POLL_SECONDS
    campaign: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = api.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 200, response.text
        campaign = response.json()
        if campaign["status"] in wanted:
            return campaign
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"campaign never reached {' or '.join(wanted)}; last: {campaign}")


def settle(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Wait until drafting ends: the run waits for approval or has failed."""
    return until_status(api, campaign_id, AWAITING, FAILED)


STREAM_TIMEOUT_SECONDS = 30


def read_events(
    api: httpx.Client, campaign_id: str, last_event_id: int | None = None
) -> list[dict[str, Any]]:
    """Read the stream until the server closes it; one dict per event."""
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    events: list[dict[str, Any]] = []
    with api.stream(
        "GET",
        f"/campaigns/{campaign_id}/events",
        headers=headers,
        timeout=STREAM_TIMEOUT_SECONDS,
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events
