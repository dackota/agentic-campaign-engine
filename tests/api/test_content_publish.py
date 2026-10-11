"""Seam 1 at fast depth: approving a campaign publishes its landing page to the CMS and its
assets to the S3 bucket, each with a receipt and a link, and a retried publish writes
nothing twice."""

import httpx

from tests.api.helpers import (
    SENT,
    bucket_keys,
    cms_page,
    cms_pages,
    create,
    receipts,
    settle,
    until_status,
)
from tests.harness.stack import Stack

ASSET_NAMES = ("email-a.html", "email-b.html")


def publish(api: httpx.Client, approver: httpx.Client) -> str:
    """Create a campaign, approve it, and wait until it is sent; the campaign id."""
    campaign_id = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)
    return str(campaign_id)


def test_landing_page_is_on_the_cms_after_approval(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = publish(api, approver)
    draft = api.get(f"/campaigns/{campaign_id}").json()["draft"]

    page = cms_page(stack, campaign_id)

    assert page["title"] == draft["subject"]
    assert page["callToAction"] == draft["call_to_action"]
    assert "Stay safe." in page["body"]


def test_assets_are_objects_in_the_bucket(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = publish(api, approver)

    keys = bucket_keys(stack, f"{campaign_id}/")

    assert sorted(keys) == sorted(f"{campaign_id}/{name}" for name in ASSET_NAMES)


def test_each_item_has_a_receipt_with_a_link(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = publish(api, approver)

    items = receipts(api, campaign_id)

    assert sorted(i["target"] for i in items) == sorted(
        ["cms", *(f"s3/{name}" for name in ASSET_NAMES)]
    )
    for item in items:
        assert item["receipt_id"]
        assert httpx.get(item["url"], timeout=10).status_code == 200, item
    cms = next(i for i in items if i["target"] == "cms")
    assert cms["url"].startswith(stack.cms_url)


def test_retried_publish_creates_no_duplicates(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.drop_next_content_replies()  # each store keeps the first write, answers 503

    campaign_id = publish(api, approver)

    assert [p["slug"] for p in cms_pages(stack) if p["slug"] == campaign_id] == [campaign_id]
    assert cms_page(stack, campaign_id)["writes"] > 1  # the retry reached the CMS
    assert len(bucket_keys(stack, f"{campaign_id}/")) == len(ASSET_NAMES)
    assert len(receipts(api, campaign_id)) == 1 + len(ASSET_NAMES)
