"""Slack and Google Docs are on by flag. With their credentials set and the fake Slack and
fake Google in-process, the approval request and the publish notice reach Slack and one
Google Doc holds the brief and the drafts. With no credentials, or a service that refuses or
is down, nothing errors and nothing is sent."""

import asyncio

import httpx
from campaign_worker import notify
from campaign_worker.activities import Activities
from fake_google.app import GoogleConfig
from fake_google.app import create_app as create_google
from fake_slack.app import SlackConfig
from fake_slack.app import create_app as create_slack
from sqlalchemy.engine import Engine

from tests.support.dag import REPORT
from tests.support.fake_services import FakeServices
from tests.support.scripted_outputs import scripted_output
from tests.support.seed import CampaignSeed, seed_campaign
from tests.support.settings import unit_settings

SLACK_TOKEN = "xoxb-test-token"
CHANNEL = "#campaigns"
WEB_URL = "https://ace.example.com"
GOOGLE = GoogleConfig(client_id="gid", client_secret="gsecret", refresh_token="grefresh")
DRAFT_A = scripted_output("email_writer")
DRAFT_B = scripted_output("email_writer", variant=1)
ON = {
    "slack_token": SLACK_TOKEN,
    "slack_channel": CHANNEL,
    "slack_url": "http://slack",
    "web_url": WEB_URL,
    "google_client_id": "gid",
    "google_client_secret": "gsecret",
    "google_refresh_token": "grefresh",
    "google_token_url": "http://google/token",
    "google_docs_url": "http://google",
}


class Integrations:
    """A drafted campaign, the worker that announces it, and the fake Slack and Google it
    announces to."""

    def __init__(self, engine: Engine, **settings: object) -> None:
        self.campaign = str(
            seed_campaign(engine, CampaignSeed(draft=DRAFT_A, variant_b=DRAFT_B, status="sending"))
        )
        self.services = FakeServices(
            {
                "slack": create_slack(SlackConfig(SLACK_TOKEN)),
                "google": create_google(GOOGLE),
            }
        )
        self.settings = unit_settings(**{**ON, **settings})
        self.activities = Activities(self.settings, engine, self.services)

    def slack_messages(self) -> list[dict[str, str]]:
        return self._read("http://slack/_messages")

    def google_docs(self) -> list[dict[str, str]]:
        return self._read("http://google/_documents")

    def _read(self, url: str) -> list[dict[str, str]]:
        async def get() -> list[dict[str, str]]:
            async with self.services.client() as client:
                found: list[dict[str, str]] = (await client.get(url)).json()
                return found

        return asyncio.run(get())

    def calls_made(self) -> int:
        return len(self.services.seen)


def test_slack_gets_the_approval_request_and_the_publish_notice(sqlite_engine: Engine) -> None:
    run = Integrations(sqlite_engine)

    asyncio.run(run.activities.announce_approval(run.campaign))
    asyncio.run(run.activities.announce_published(run.campaign, "receipt-77"))

    approval, published = run.slack_messages()
    assert "approval" in approval["text"].lower() and run.campaign in approval["text"]
    assert "sent" in published["text"].lower()
    assert run.campaign in published["text"] and "receipt-77" in published["text"]
    assert {m["channel"] for m in run.slack_messages()} == {CHANNEL}
    assert SLACK_TOKEN not in str(run.slack_messages())


def test_the_approval_message_links_to_the_inbox_item(sqlite_engine: Engine) -> None:
    run = Integrations(sqlite_engine)

    asyncio.run(run.activities.announce_approval(run.campaign))

    [approval] = run.slack_messages()
    assert approval["text"].endswith(f"{WEB_URL}/?inbox={run.campaign}")
    assert REPORT.splitlines()[0] in approval["text"]


def test_the_google_stand_in_gets_one_doc_with_the_brief_and_both_drafts(
    sqlite_engine: Engine,
) -> None:
    run = Integrations(sqlite_engine)

    asyncio.run(run.activities.announce_published(run.campaign, "receipt-77"))

    [doc] = run.google_docs()
    assert REPORT.strip() in doc["text"]
    assert DRAFT_A["subject"] in doc["text"] and DRAFT_B["subject"] in doc["text"]
    assert "Variant A" in doc["text"] and "Variant B" in doc["text"]


def test_with_no_credentials_nothing_is_called_and_nothing_errors(sqlite_engine: Engine) -> None:
    run = Integrations(
        sqlite_engine,
        slack_token="",
        google_client_id="",
        google_client_secret="",
        google_refresh_token="",
    )

    asyncio.run(run.activities.announce_approval(run.campaign))
    asyncio.run(run.activities.announce_published(run.campaign, "receipt-77"))

    assert run.calls_made() == 0
    assert not run.settings.slack_enabled and not run.settings.google_enabled


def test_slack_alone_is_off_without_a_channel_and_google_alone_is_off_without_a_secret() -> None:
    assert not unit_settings(slack_token=SLACK_TOKEN).slack_enabled
    assert not unit_settings(slack_channel=CHANNEL).slack_enabled
    assert not unit_settings(**{**ON, "google_client_secret": ""}).google_enabled
    assert unit_settings(**ON).slack_enabled and unit_settings(**ON).google_enabled


def test_a_slack_that_refuses_the_token_gets_false_and_stores_nothing(
    sqlite_engine: Engine,
) -> None:
    run = Integrations(sqlite_engine, slack_token="wrong-token")

    async def post() -> bool:
        async with run.services.client() as client:
            return await notify.post_to_slack(client, run.settings, "hello")

    assert asyncio.run(post()) is False
    assert run.slack_messages() == []


def test_a_google_that_refuses_the_credentials_exports_nothing_and_does_not_raise(
    sqlite_engine: Engine,
) -> None:
    run = Integrations(sqlite_engine, google_client_secret="wrong-secret")

    async def export() -> str | None:
        async with run.services.client() as client:
            return await notify.export_to_google_doc(client, run.settings, "t", "text")

    assert asyncio.run(export()) is None
    assert run.google_docs() == []


def test_a_slack_or_google_outage_does_not_raise() -> None:
    settings = unit_settings(**ON)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async def notify_both() -> tuple[bool, str | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
            return (
                await notify.post_to_slack(client, settings, "hello"),
                await notify.export_to_google_doc(client, settings, "t", "text"),
            )

    assert asyncio.run(notify_both()) == (False, None)


def test_the_inbox_link_is_the_web_apps_inbox_and_empty_without_a_web_url() -> None:
    assert notify.inbox_link(unit_settings(web_url="https://a.example/"), "c-1") == (
        "https://a.example/?inbox=c-1"
    )
    assert notify.inbox_link(unit_settings(web_url=""), "c-1") == ""


def test_the_summary_line_is_the_first_filled_line_cut_to_the_limit() -> None:
    assert notify.first_line("\n  \n  Volt Typhoon  \nsecond") == "Volt Typhoon"
    assert len(notify.first_line("x" * 500)) == notify.SUMMARY_LINE_LIMIT
    assert notify.first_line("") == ""


def test_slack_or_google_switched_off_makes_no_call() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no call expected, got {request.url}")

    async def notify_both() -> tuple[bool, str | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
            return (
                await notify.post_to_slack(client, unit_settings(), "hello"),
                await notify.export_to_google_doc(client, unit_settings(), "t", "text"),
            )

    assert asyncio.run(notify_both()) == (False, None)
