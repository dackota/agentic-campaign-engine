"""`alerts.post_to_slack` posts through the client it is given, so a unit test reads the post."""

import asyncio
import json

import httpx
from campaign_api import alerts

from tests.support.settings import unit_settings

SETTINGS = unit_settings(
    slack_token="xoxb-secret", slack_channel="#alerts", slack_url="http://s.invalid"
)


def test_a_notice_is_posted_to_the_channel_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async def post() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await alerts.post_to_slack(SETTINGS, "ALERT firing: x", client)

    asyncio.run(post())

    [request] = seen
    assert request.url == "http://s.invalid/chat.postMessage"
    assert request.headers["Authorization"] == "Bearer xoxb-secret"
    assert json.loads(request.content) == {"channel": "#alerts", "text": "ALERT firing: x"}


def test_a_slack_outage_is_dropped_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async def post() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await alerts.post_to_slack(SETTINGS, "ALERT firing: x", client)

    asyncio.run(post())


def test_slack_off_posts_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no call expected")

    async def post() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await alerts.post_to_slack(unit_settings(), "x", client)

    asyncio.run(post())
