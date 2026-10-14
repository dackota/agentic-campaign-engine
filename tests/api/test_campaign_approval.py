"""Seam 1 at fast depth: the happy path. The run waits for approval after the draft; a Demand
Gen approver approves it; the approval sends once through the fake Marketo, and every publish
target (Marketo, Workfront, the CMS, the S3 asset store) holds its item and gives the campaign
a receipt. That nothing sends without approval, that approving twice sends once, a failed or
untrustworthy send, and the receipts' contracts are proved lower: see
tests/engine/test_workflow_approval.py, test_campaign_routes.py and tests/fakes/."""

import httpx

from tests.api.helpers import (
    AWAITING,
    SENT,
    bucket_keys,
    cms_page,
    create,
    receipts,
    settle,
    until_status,
    workfront_tasks,
)
from tests.api.helpers import marketo_sends as sends
from tests.harness.stack import Stack

EXPECTED_TARGETS = {"marketo", "workfront", "cms", "s3/email-a.html", "s3/email-b.html"}
RECEIPT_TIMEOUT_SECONDS = 10


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
    assert delivered[0]["receiptId"] == sent["receipt"]
    assert delivered[0]["variants"][0]["subject"] == sent["draft"]["subject"]
    held = {r["target"]: r for r in receipts(api, campaign_id)}
    assert set(held) == EXPECTED_TARGETS
    assert held["marketo"]["receipt_id"] == sent["receipt"]
    [task] = workfront_tasks(stack, campaign_id)
    assert held["workfront"]["receipt_id"] == task["ID"]
    assert task["ID"] in held["workfront"]["url"]
    assert cms_page(stack, campaign_id)["title"] == sent["draft"]["subject"]
    assert sorted(bucket_keys(stack, f"{campaign_id}/")) == sorted(
        f"{campaign_id}/{t.removeprefix('s3/')}" for t in EXPECTED_TARGETS if t.startswith("s3/")
    )
    for target in ("cms", "s3/email-a.html", "s3/email-b.html"):
        link = httpx.get(held[target]["url"], timeout=RECEIPT_TIMEOUT_SECONDS)
        assert link.status_code == 200, (target, held[target]["url"])
