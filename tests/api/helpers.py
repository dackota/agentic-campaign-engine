"""Helpers the Campaign API tests share: make a campaign, wait for it to reach a status."""

import hashlib
import hmac
import time
from typing import Any

import httpx

from tests.harness.stack import Stack

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


# The fake Marketo, read from the outside through its own REST API.
MARKETO_TOKEN_PATH = "/identity/oauth/token"
MARKETO_PROGRAMS_PATH = "/rest/asset/v1/programs.json"
MARKETO_HTTP_TIMEOUT_SECONDS = 10
# Activity webhooks: the HMAC-SHA256 of "<timestamp>." + body, hex, in this header.
MARKETO_WEBHOOK_PATH = "/webhooks/marketo"
SIGNATURE_HEADER = "X-Marketo-Signature"
TIMESTAMP_HEADER = "X-Marketo-Timestamp"


def marketo_token(marketo_url: str, client_id: str, client_secret: str) -> httpx.Response:
    return httpx.post(
        f"{marketo_url}{MARKETO_TOKEN_PATH}",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )


def marketo_programs(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """The programs the fake Marketo holds for this campaign, each with its sends."""
    token = marketo_token(stack.marketo_url, stack.marketo_client_id, stack.marketo_client_secret)
    assert token.status_code == 200, token.text
    response = httpx.get(
        f"{stack.marketo_url}{MARKETO_PROGRAMS_PATH}",
        params={"externalId": campaign_id},
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    programs: list[dict[str, Any]] = body["result"]
    return programs


def marketo_sends(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """Every send the fake Marketo made for this campaign, across its programs."""
    return [send for p in marketo_programs(stack, campaign_id) for send in p["sends"]]


def signed_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Headers that sign `body` the way the fake Marketo signs its activity webhooks."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {
        TIMESTAMP_HEADER: stamp,
        SIGNATURE_HEADER: f"sha256={digest.hexdigest()}",
        "Content-Type": "application/json",
    }
