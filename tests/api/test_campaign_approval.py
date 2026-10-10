"""Seam 1 at fast depth: nothing sends until a human approves; approval sends once through
the fake Marketo and the campaign shows a receipt. A Demand Gen owner creates each
campaign and a Demand Gen approver approves it."""

import time
import uuid
from typing import Any

import httpx

from tests.api.helpers import AWAITING, FAILED, SENT, create, settle, until_status
from tests.harness.stack import Stack

QUIET_SECONDS = 1.5


def sends(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """What the fake Marketo delivered for this campaign (the stack is shared by tests)."""
    response = httpx.get(f"{stack.marketo_url}/_sends", timeout=10)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return [s for s in body if s["campaign_id"] == campaign_id]


def test_run_waits_for_approval_after_draft_and_api_can_approve(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]

    waiting = settle(api, campaign_id)
    assert waiting["status"] == AWAITING
    assert waiting["receipt"] is None
    assert sends(stack, campaign_id) == []

    response = approver.post(f"/campaigns/{campaign_id}/approve")
    assert response.status_code == 202, response.text

    sent = until_status(api, campaign_id, SENT)
    assert sent["receipt"]
    delivered = sends(stack, campaign_id)
    assert len(delivered) == 1
    assert delivered[0]["receipt"] == sent["receipt"]
    assert delivered[0]["subject"] == sent["draft"]["subject"]


def test_no_send_happens_without_approval(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    assert settle(api, campaign_id)["status"] == AWAITING

    time.sleep(QUIET_SECONDS)

    assert api.get(f"/campaigns/{campaign_id}").json()["status"] == AWAITING
    assert sends(stack, campaign_id) == []


def test_approving_twice_or_a_campaign_not_waiting_never_sends_again(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)

    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 409
    assert approver.post(f"/campaigns/{uuid.uuid4()}/approve").status_code == 404
    assert len(sends(stack, campaign_id)) == 1


def test_failed_campaign_cannot_be_approved(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.agent.script(["not json", "still not json"])
    campaign_id = create(api)["id"]
    assert settle(api, campaign_id)["status"] == FAILED

    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 409
    assert sends(stack, campaign_id) == []


def test_worker_restart_during_the_wait_does_not_lose_the_run(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    assert settle(api, campaign_id)["status"] == AWAITING

    stack.restart_worker()

    assert api.get(f"/campaigns/{campaign_id}").json()["status"] == AWAITING
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)
    assert sent["receipt"]
    assert len(sends(stack, campaign_id)) == 1


def test_invalid_marketo_reply_fails_the_campaign_naming_the_reply(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    assert settle(api, campaign_id)["status"] == AWAITING

    stack.marketo_malformed_reply(True)
    try:
        assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
        failed = until_status(api, campaign_id, FAILED)
    finally:
        stack.marketo_malformed_reply(False)

    assert "Marketo" in failed["failure_reason"]
    assert "receiptId" in failed["failure_reason"]
    assert failed["receipt"] is None
