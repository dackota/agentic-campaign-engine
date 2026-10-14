"""Approving a campaign publishes its landing page to the CMS and its email assets to the S3
bucket, each with a receipt and a link, and a retried publish writes nothing twice. The
worker's publish activity runs against the real fake CMS and fake S3 in-process."""

import asyncio
import re
from typing import Any
from xml.etree import ElementTree

import httpx
from campaign_worker.activities import Activities
from fake_cms.app import create_app as create_cms
from fake_s3.app import create_app as create_s3
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.fake_services import FakeServices
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import CampaignSeed, seed_campaign
from tests.support.settings import unit_settings

S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
BUCKET = "ace-assets"
ASSET_NAMES = ("email-a.html", "email-b.html")
EMAILS = [scripted_output("email_writer"), scripted_output("email_writer", variant=1)]
OWNER = {"Authorization": "Bearer dg-owner@demo.example"}


class Published:
    """A campaign ready to publish, the worker that publishes it, and the fakes it writes to."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.id = str(seed_campaign(engine, CampaignSeed(draft=EMAILS[0])))
        self.services = FakeServices({"cms": create_cms(), "s3": create_s3()})
        settings = unit_settings(cms_url="http://cms", s3_url="http://s3", s3_bucket=BUCKET)
        self.activities = Activities(settings, engine, self.services)

    async def publish(self) -> None:
        await self.activities.publish_content(self.id, EMAILS)

    async def publish_until_it_succeeds(self, attempts: int) -> int:
        """Run the activity as Temporal retries it; the number of attempts it took."""
        for attempt in range(1, attempts + 1):
            try:
                await self.publish()
            except httpx.HTTPStatusError:
                continue
            return attempt
        raise AssertionError(f"still failing after {attempts} attempts")

    async def get(self, url: str) -> httpx.Response:
        async with self.services.client() as client:
            return await client.get(url)

    async def drop_next_replies(self) -> None:
        """Each store keeps the next write it gets and answers 503."""
        async with self.services.client() as client:
            for host in ("cms", "s3"):
                await client.put(f"http://{host}/_fault", json={"drop_next_reply": True})

    async def bucket_keys(self) -> list[str]:
        listing = await self.get(f"http://s3/{BUCKET}?list-type=2&prefix={self.id}/")
        return [
            k.text or "" for k in ElementTree.fromstring(listing.text).iter(f"{S3_NAMESPACE}Key")
        ]


def test_landing_page_is_on_the_cms_after_publishing(sqlite_engine: Engine) -> None:
    published = Published(sqlite_engine)

    async def run() -> dict[str, str]:
        await published.publish()
        page: dict[str, str] = (await published.get(f"http://cms/api/pages/{published.id}")).json()[
            "data"
        ]
        return page

    page = asyncio.run(run())

    assert page["title"] == EMAILS[0]["subject"]
    assert page["callToAction"] == EMAILS[0]["call_to_action"]
    assert "Stay safe." in page["body"]


def test_email_assets_are_objects_in_the_bucket(sqlite_engine: Engine) -> None:
    published = Published(sqlite_engine)

    async def run() -> list[str]:
        await published.publish()
        return await published.bucket_keys()

    assert sorted(asyncio.run(run())) == sorted(f"{published.id}/{name}" for name in ASSET_NAMES)


def test_each_item_has_a_receipt_with_a_link_the_campaign_shows(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    published = Published(sqlite_engine)

    async def run() -> list[httpx.Response]:
        await published.publish()
        items = app_client.get(f"/campaigns/{published.id}", headers=OWNER).json()["receipts"]
        return [await published.get(i["url"]) for i in items]

    links = asyncio.run(run())
    items = app_client.get(f"/campaigns/{published.id}", headers=OWNER).json()["receipts"]

    assert sorted(i["target"] for i in items) == sorted(
        ["cms", *(f"s3/{name}" for name in ASSET_NAMES)]
    )
    assert all(i["receipt_id"] for i in items)
    assert [r.status_code for r in links] == [200, 200, 200]
    [cms] = [i for i in items if i["target"] == "cms"]
    assert cms["url"] == f"http://cms/api/pages/{published.id}"
    assert re.fullmatch(r"cms-\d+", cms["receipt_id"])


def test_retried_publish_creates_no_duplicates(
    sqlite_engine: Engine, app_client: TestClient
) -> None:
    published = Published(sqlite_engine)

    async def run() -> tuple[int, list[dict[str, Any]], list[str]]:
        await published.drop_next_replies()
        attempts = await published.publish_until_it_succeeds(attempts=4)
        pages = (await published.get("http://cms/api/pages")).json()["data"]
        return attempts, pages, await published.bucket_keys()

    attempts, pages, keys = asyncio.run(run())
    receipts = app_client.get(f"/campaigns/{published.id}", headers=OWNER).json()["receipts"]

    assert attempts > 1  # the first replies were lost
    assert [p["slug"] for p in pages if p["slug"] == published.id] == [published.id]
    [page] = [p for p in pages if p["slug"] == published.id]
    assert page["writes"] > 1  # the retry reached the CMS
    assert len(keys) == len(ASSET_NAMES)
    assert len(receipts) == 1 + len(ASSET_NAMES)
