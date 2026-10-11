"""Seam 1 at fast depth: a task status change in the fake Workfront reaches the campaign by
signed webhook. The endpoint takes a body only when its HMAC signature is right and fresh,
records each event id once, and answers anything malformed with a 4xx, never a 5xx."""

import json
import time
import uuid
from typing import Any

import httpx

from tests.api.helpers import (
    SENT,
    WORKFRONT_TARGET,
    WORKFRONT_WEBHOOK_PATH,
    create,
    settle,
    until_status,
    workfront_client,
    workfront_signed_headers,
)
from tests.harness.stack import Stack

POLL_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.2
STALE_SECONDS = 3600


def event(campaign_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "taskID": "task-1",
        "campaignId": campaign_id,
        "status": "INP",
        **overrides,
    }


def post(api: httpx.Client, body: bytes, headers: dict[str, str]) -> httpx.Response:
    return api.post(WORKFRONT_WEBHOOK_PATH, content=body, headers=headers)


def until_task_status(api: httpx.Client, campaign_id: str, wanted: str) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_SECONDS
    campaign: dict[str, Any] = {}
    while time.monotonic() < deadline:
        campaign = api.get(f"/campaigns/{campaign_id}").json()
        if campaign.get("task_status") == wanted:
            return campaign
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"task status never became {wanted}; last: {campaign}")


def test_status_change_in_the_fake_shows_on_the_campaign(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)
    [receipt] = [r for r in sent["receipts"] if r["target"] == WORKFRONT_TARGET]

    with workfront_client(stack) as client:
        first = client.put(f"/task/{receipt['receipt_id']}", json={"status": "INP"})
        assert first.status_code == 200, first.text
    until_task_status(api, campaign_id, "INP")
    with workfront_client(stack) as client:
        client.put(f"/task/{receipt['receipt_id']}", json={"status": "CPL"})
    done = until_task_status(api, campaign_id, "CPL")

    assert done["status"] == SENT


def test_signed_webhook_is_accepted_and_shows_on_the_campaign(
    stack: Stack, api: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id, status="CLS")).encode()

    response = post(api, body, workfront_signed_headers(stack.workfront_webhook_secret, body))

    assert 200 <= response.status_code < 300, response.text
    until_task_status(api, campaign_id, "CLS")


def test_bad_signature_or_stale_timestamp_is_401_and_not_recorded(
    stack: Stack, api: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id)).encode()
    wrong_key = workfront_signed_headers("not-the-webhook-secret", body)
    stale = workfront_signed_headers(
        stack.workfront_webhook_secret, body, int(time.time()) - STALE_SECONDS
    )

    assert post(api, body, wrong_key).status_code == 401
    assert post(api, body, stale).status_code == 401
    assert post(api, body, {"Content-Type": "application/json"}).status_code == 401
    assert api.get(f"/campaigns/{campaign_id}").json()["task_status"] is None


def test_replayed_id_is_409(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id)).encode()
    first = post(api, body, workfront_signed_headers(stack.workfront_webhook_secret, body))
    assert 200 <= first.status_code < 300, first.text

    again = post(api, body, workfront_signed_headers(stack.workfront_webhook_secret, body))

    assert again.status_code == 409


def test_malformed_bodies_are_4xx_never_5xx(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    good = event(campaign_id)
    bodies = [
        b"",
        b"null",
        b"[]",
        b"{}",
        b"{not json",
        b"\xff\xfe\x00garbage",
        b"x" * (256 * 1024),
        json.dumps({**good, "id": ""}).encode(),
        json.dumps({**good, "status": None}).encode(),
        json.dumps({**good, "status": "x" * 500}).encode(),
        json.dumps({**good, "campaignId": "not-a-uuid"}).encode(),
        json.dumps({**good, "campaignId": str(uuid.uuid4())}).encode(),
    ]

    for body in bodies:
        signed = post(api, body, workfront_signed_headers(stack.workfront_webhook_secret, body))
        assert 400 <= signed.status_code < 500, (body[:60], signed.status_code)
    assert api.get(f"/campaigns/{campaign_id}").json()["task_status"] is None
