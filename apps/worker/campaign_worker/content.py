"""The CMS and asset-library publisher adapters: the landing page goes to the CMS, and each
email variant goes to the S3 bucket as an HTML asset.

Both writes are idempotent by key (the page by its slug, the object by its key), so a
retried publish replaces an item with itself and never adds a second one."""

import asyncio
from html import escape
from typing import Any

import httpx
from ace_engine.settings import Settings
from render_service.email import EmailTooLarge, render_email
from temporalio.exceptions import ApplicationError

from campaign_worker.publisher import Adapter, ApprovedCampaign, Receipt

CMS_TARGET = "cms"
S3_TARGET_PREFIX = "s3/"
CONTENT_REPLY_INVALID = "ContentReplyInvalid"
ASSET_TOO_LARGE = "AssetTooLarge"
PAGES_PATH = "/api/pages"
ASSET_NAMES = ("email-a.html", "email-b.html")
HTML_TYPE = "text/html; charset=utf-8"


class CmsAdapter:
    target = CMS_TARGET

    def __init__(self, cms_url: str) -> None:
        self._url = cms_url.rstrip("/")

    async def publish(
        self, client: httpx.AsyncClient, campaign: ApprovedCampaign, idempotency_key: str
    ) -> Receipt:
        variant_a = campaign.emails[0]
        page_url = f"{self._url}{PAGES_PATH}/{campaign.campaign_id}"
        response = await client.put(
            page_url,
            json={
                "title": variant_a["subject"],
                "body": f"<p>{escape(variant_a['body'])}</p>",
                "callToAction": variant_a["call_to_action"],
            },
        )
        response.raise_for_status()
        try:
            page_id = response.json()["data"]["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise _invalid(f"CMS reply has no page id: {response.text[:200]!r}") from exc
        return Receipt(target=CMS_TARGET, receipt_id=f"cms-{page_id}", url=page_url)


class AssetAdapter:
    def __init__(self, s3_url: str, bucket: str, name: str, email_index: int) -> None:
        self._url = s3_url.rstrip("/")
        self._bucket = bucket
        self._name = name
        self._email_index = email_index
        self.target = f"{S3_TARGET_PREFIX}{name}"

    async def publish(
        self, client: httpx.AsyncClient, campaign: ApprovedCampaign, idempotency_key: str
    ) -> Receipt:
        try:
            html = await asyncio.to_thread(render_email, campaign.emails[self._email_index])
        except EmailTooLarge as exc:
            raise ApplicationError(str(exc), type=ASSET_TOO_LARGE, non_retryable=True) from exc
        made = await client.put(f"{self._url}/{self._bucket}")
        made.raise_for_status()
        object_url = f"{self._url}/{self._bucket}/{campaign.campaign_id}/{self._name}"
        stored = await client.put(
            object_url, content=html.encode(), headers={"Content-Type": HTML_TYPE}
        )
        stored.raise_for_status()
        etag = stored.headers.get("ETag", "").strip('"')
        if not etag:
            raise _invalid(f"S3 reply has no ETag for {self._name}")
        return Receipt(target=self.target, receipt_id=etag, url=object_url)


def content_adapters(settings: Settings, emails: tuple[dict[str, Any], ...]) -> list[Adapter]:
    """The adapters for the targets this deployment has a URL for."""
    adapters: list[Adapter] = []
    if settings.cms_url.strip():
        adapters.append(CmsAdapter(settings.cms_url))
    if settings.s3_url.strip():
        adapters.extend(
            AssetAdapter(settings.s3_url, settings.s3_bucket, name, index)
            for index, name in enumerate(ASSET_NAMES[: len(emails)])
        )
    return adapters


def _invalid(message: str) -> ApplicationError:
    return ApplicationError(message, type=CONTENT_REPLY_INVALID, non_retryable=True)
