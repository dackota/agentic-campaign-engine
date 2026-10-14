"""The engine, not the design agent, saves the two social cards to the asset library, once
each: the worker's save activity against the real fake S3 in-process."""

import asyncio
from xml.etree import ElementTree

import httpx
import pytest
from ace_engine import db
from campaign_worker import cards
from campaign_worker.activities import Activities
from campaign_worker.publisher import Receipt
from fake_s3.app import create_app as create_s3
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.exceptions import ApplicationError

from tests.support.fake_services import FakeServices
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import seed_campaign
from tests.support.settings import unit_settings

S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
BUCKET = "ace-assets"
CARD_NAMES = ("social-card-1.svg", "social-card-2.svg")
SETTINGS = unit_settings(s3_url="http://s3", s3_bucket=BUCKET)


class Library:
    """A campaign with its design output, the worker that saves it, and the S3 it saves to."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.campaign = seed_campaign(engine)
        self.output = scripted_output("design")
        self.s3 = FakeServices({"s3": create_s3()})
        self.activities = Activities(SETTINGS, engine, self.s3)

    async def save(self) -> None:
        await self.activities.save_cards(str(self.campaign), self.output)

    async def keys(self) -> list[str]:
        async with self.s3.client() as client:
            listing = await client.get(
                f"http://s3/{BUCKET}?list-type=2&prefix=cards/{self.campaign}/"
            )
        root = ElementTree.fromstring(listing.text)
        return [k.text or "" for k in root.iter(f"{S3_NAMESPACE}Key")]

    def receipts(self) -> list[tuple[str, str]]:
        with Session(self.engine) as session:
            found = db.receipts_by_campaign(session, [self.campaign]).get(self.campaign, [])
            return [(r.target, r.url) for r in found]


def test_the_engine_saves_both_cards_to_the_asset_library(sqlite_engine: Engine) -> None:
    library = Library(sqlite_engine)

    async def run() -> tuple[list[str], list[httpx.Response]]:
        await library.save()
        async with library.s3.client() as client:
            stored = [await client.get(url) for _, url in library.receipts()]
        return await library.keys(), stored

    keys, stored = asyncio.run(run())

    assert sorted(keys) == sorted(f"cards/{library.campaign}/{n}" for n in CARD_NAMES)
    assert sorted(t for t, _ in library.receipts()) == sorted(f"cards/{n}" for n in CARD_NAMES)
    assert [r.status_code for r in stored] == [200, 200]
    assert all(r.text.startswith("<svg") for r in stored)


def test_a_retried_save_adds_no_second_card(sqlite_engine: Engine) -> None:
    library = Library(sqlite_engine)

    async def run() -> list[str]:
        async with library.s3.client() as client:
            await client.put("http://s3/_fault", json={"drop_next_reply": True})
        with pytest.raises(httpx.HTTPStatusError):  # the store kept the card, then answered 503
            await library.save()
        await library.save()
        return await library.keys()

    keys = asyncio.run(run())

    assert len(keys) == len(CARD_NAMES)
    assert len(library.receipts()) == len(CARD_NAMES)


def test_a_store_reply_with_no_etag_fails_the_step_without_a_retry() -> None:
    def no_etag(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def save() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_etag)) as client:
            await cards.save_cards(client, SETTINGS, "c-1", scripted_output("design"))

    with pytest.raises(ApplicationError) as failure:
        asyncio.run(save())

    assert failure.value.type == cards.CARD_REPLY_INVALID
    assert failure.value.non_retryable


def test_no_asset_library_saves_nothing() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no call expected")

    async def save() -> list[Receipt]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
            return await cards.save_cards(
                client, unit_settings(s3_url=""), "c-1", scripted_output("design")
            )

    assert asyncio.run(save()) == []
