"""`Activities` sends through the transport it is given, so a unit test reads the requests."""

import asyncio
import uuid

import httpx
from ace_engine import db
from campaign_worker.activities import Activities
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.settings import unit_settings

S3_URL = "http://s3.invalid"
BUCKET = "ace-assets"
CAMPAIGN_ID = str(uuid.uuid4())


def test_save_cards_sends_each_card_through_the_given_transport(sqlite_engine: Engine) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"ETag": '"abc"'})

    settings = unit_settings(s3_url=S3_URL, s3_bucket=BUCKET)
    activities = Activities(settings, sqlite_engine, httpx.MockTransport(handler))

    asyncio.run(
        activities.save_cards(CAMPAIGN_ID, {"cards": [{"name": "one.svg", "svg": "<svg/>"}]})
    )

    assert [(r.method, r.url.path) for r in seen] == [
        ("PUT", f"/{BUCKET}"),
        ("PUT", f"/{BUCKET}/cards/{CAMPAIGN_ID}/one.svg"),
    ]
    assert seen[1].content == b"<svg/>"
    with Session(sqlite_engine) as session:
        assert [r.target for r in session.scalars(select(db.Receipt))] == ["cards/one.svg"]
