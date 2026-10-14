"""Seam 1 at fast depth: a task status change in the fake Workfront reaches the campaign by
signed webhook, over real sockets. The endpoint's signature, replay, size and malformed-body
rules are proved in process: tests/engine/test_activity_webhooks.py and test_webhook_verify.py."""

import time
from typing import Any

import httpx

from tests.api.helpers import (
    SENT,
    WORKFRONT_TARGET,
    create,
    settle,
    until_status,
    workfront_client,
)
from tests.harness.stack import Stack

POLL_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.2


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
