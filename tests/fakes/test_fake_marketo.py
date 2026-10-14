"""The fake Marketo, in process: it speaks OAuth2 client credentials, holds programs, and
takes A/B sends. One approval publishes one program with one send of both variants, a retried
publish never sends twice, and the signed activities it posts verify with the Campaign API's
rules. The worker's own Marketo adapter drives it through an ASGI transport."""

import asyncio
import json
import threading
import time
from typing import Any

import httpx
import pytest
from ace_engine import webhooks
from campaign_worker.marketo import MarketoAdapter
from campaign_worker.publisher import ApprovedCampaign, Receipt
from fake_marketo import app as fake_marketo
from fake_marketo.app import MarketoConfig
from fastapi.testclient import TestClient
from temporalio.exceptions import ApplicationError

from tests.support.dag import GOOD_DRAFT
from tests.support.settings import unit_settings

CLIENT_ID = "marketo-id"
CLIENT_SECRET = "marketo-secret"
WEBHOOK_SECRET = "marketo-webhook-secret"
BASE_URL = "http://marketo.test"
CAMPAIGN_ID = "11111111-2222-3333-4444-555555555555"
STEP_KEY = f"campaign-{CAMPAIGN_ID}:publish"
CONFIG = MarketoConfig(CLIENT_ID, CLIENT_SECRET, "http://127.0.0.1:9/dead", WEBHOOK_SECRET)
SETTINGS = unit_settings(
    marketo_url=BASE_URL, marketo_client_id=CLIENT_ID, marketo_client_secret=CLIENT_SECRET
)
APPROVED = ApprovedCampaign(
    CAMPAIGN_ID, (GOOD_DRAFT, {**GOOD_DRAFT, "subject": "Another subject"}), STEP_KEY
)
TOKEN_PATH = "/identity/oauth/token"
POST_WAIT_SECONDS = 5
POLL_SECONDS = 0.01
PROGRAMS_PATH = "/rest/asset/v1/programs.json"


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The activity events the fake would post to its webhook: no thread dials out."""
    seen: list[dict[str, Any]] = []
    lock = threading.Lock()

    def record(_config: MarketoConfig, events: list[dict[str, Any]]) -> None:
        with lock:
            seen.extend(events)

    monkeypatch.setattr(fake_marketo, "_post_activity", record)
    monkeypatch.setattr(fake_marketo, "_deliver_engagement", lambda *_: None)
    return seen


def _until_posted(seen: list[dict[str, Any]], count: int) -> None:
    """Wait for the fake's background thread to post `count` events."""
    deadline = time.monotonic() + POST_WAIT_SECONDS
    while len(seen) < count and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)


def _token(
    client: TestClient, client_id: str = CLIENT_ID, secret: str = CLIENT_SECRET
) -> httpx.Response:
    response: httpx.Response = client.post(
        TOKEN_PATH,
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
    )
    return response


def _programs(client: TestClient) -> list[dict[str, Any]]:
    token = _token(client).json()["access_token"]
    response = client.get(
        PROGRAMS_PATH,
        params={"externalId": CAMPAIGN_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["result"]
    return found


def _publish(client: TestClient) -> Receipt:
    async def publish() -> Receipt:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport) as http:
            return await MarketoAdapter(SETTINGS).publish(http, APPROVED, STEP_KEY)

    return asyncio.run(publish())


@pytest.fixture
def marketo(posted: list[dict[str, Any]]) -> TestClient:
    return TestClient(fake_marketo.create_app(CONFIG))


def test_token_route_issues_a_token_for_good_client_credentials(marketo: TestClient) -> None:
    response = _token(marketo)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] > 0


def test_token_route_rejects_bad_client_credentials(marketo: TestClient) -> None:
    wrong_secret = _token(marketo, secret="not-the-secret")
    wrong_client = _token(marketo, client_id="someone-else")

    assert wrong_secret.status_code == 401
    assert wrong_client.status_code == 401
    assert "access_token" not in wrong_secret.text


def test_rest_calls_without_a_token_are_401(marketo: TestClient) -> None:
    send = "/rest/asset/v1/program/1/abSend.json"

    assert marketo.get(PROGRAMS_PATH).status_code == 401
    assert (
        marketo.get(PROGRAMS_PATH, headers={"Authorization": "Bearer made-up"}).status_code == 401
    )
    assert marketo.post(send, json={"variants": []}).status_code == 401


def test_approval_sends_both_variants_in_one_program(
    marketo: TestClient, posted: list[dict[str, Any]]
) -> None:
    receipt = _publish(marketo)
    _until_posted(posted, 2)

    [program] = _programs(marketo)
    assert program["externalId"] == CAMPAIGN_ID
    assert program["name"] == STEP_KEY
    [send] = program["sends"]
    assert send["receiptId"] == receipt.receipt_id
    assert [v["label"] for v in send["variants"]] == ["A", "B"]
    assert send["variants"][0]["subject"] == GOOD_DRAFT["subject"]
    assert send["variants"][1]["subject"] == "Another subject"
    # One send activity per variant goes to the webhook.
    assert sorted((e["type"], e["variant"], e["campaignId"]) for e in posted) == [
        ("send", "A", CAMPAIGN_ID),
        ("send", "B", CAMPAIGN_ID),
    ]


def test_a_retried_publish_after_a_lost_reply_sends_once(marketo: TestClient) -> None:
    assert marketo.put("/_fault", json={"drop_next_send_reply": True}).status_code == 204

    with pytest.raises(httpx.HTTPStatusError) as lost:
        _publish(marketo)
    retried = _publish(marketo)

    assert lost.value.response.status_code == 503
    [program] = _programs(marketo)
    [send] = program["sends"]
    assert send["receiptId"] == retried.receipt_id


def test_a_send_reply_with_no_receipt_fails_the_publish_naming_the_reply(
    marketo: TestClient,
) -> None:
    assert marketo.put("/_fault", json={"malformed_reply": True}).status_code == 204

    with pytest.raises(ApplicationError) as failed:
        _publish(marketo)

    assert "Marketo reply has no receiptId" in failed.value.message
    assert failed.value.non_retryable is True


def test_the_activities_the_fake_posts_verify_with_the_campaign_apis_webhook_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    def post(
        url: str, *, content: bytes, headers: dict[str, str], timeout: float
    ) -> httpx.Response:
        request = httpx.Request("POST", url, content=content, headers=headers)
        captured.append(request)
        return httpx.Response(202, request=request)

    monkeypatch.setattr(httpx, "post", post)
    event = {"id": "e1", "type": "open", "campaignId": CAMPAIGN_ID, "variant": "A"}

    fake_marketo._post_activity(CONFIG, [event])

    [request] = captured
    assert json.loads(request.content) == event
    webhooks.verify(request.headers, request.content, WEBHOOK_SECRET)
    with pytest.raises(webhooks.WebhookRejected):
        webhooks.verify(request.headers, request.content, "another-secret")


def test_a_failed_activity_post_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> httpx.Response:
        raise httpx.ConnectError("nothing listens")

    monkeypatch.setattr(httpx, "post", refuse)

    fake_marketo._post_activity(CONFIG, [{"id": "e1"}])


class _Clock:
    """A clock that only moves when the code sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_a_high_time_speed_delivers_days_of_engagement_in_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    delivered: list[tuple[float, str]] = []
    day = 86_400
    timeline = [
        (0, {"id": "first"}),
        (day // 2, {"id": "half-a-day"}),
        (2 * day, {"id": "two-days"}),
    ]

    def record(_config: MarketoConfig, events: list[dict[str, Any]]) -> None:
        delivered.extend((clock.now, e["id"]) for e in events)

    monkeypatch.setattr(fake_marketo, "time", clock)
    monkeypatch.setattr(fake_marketo, "_post_activity", record)

    fake_marketo._deliver_engagement(CONFIG, timeline, 100_000.0)

    assert [event for _, event in delivered] == ["first", "half-a-day", "two-days"]
    # Two simulated days take 1.728 real seconds at 100 000 times speed.
    assert delivered[-1][0] == pytest.approx(2 * day / 100_000.0)
    assert delivered[-1][0] < 2


@pytest.mark.parametrize("time_speed", [1.0, 1_000.0, 1e9])
def test_each_event_waits_for_its_simulated_time_divided_by_the_speed(
    monkeypatch: pytest.MonkeyPatch, time_speed: float
) -> None:
    clock = _Clock()
    delivered_at: list[float] = []
    seconds = [10, 400, 4_000]
    timeline = [(s, {"id": str(s)}) for s in seconds]

    def record(_config: MarketoConfig, _events: list[dict[str, Any]]) -> None:
        delivered_at.append(clock.now)

    monkeypatch.setattr(fake_marketo, "time", clock)
    monkeypatch.setattr(fake_marketo, "_post_activity", record)

    fake_marketo._deliver_engagement(CONFIG, timeline, time_speed)

    assert delivered_at == [pytest.approx(s / time_speed) for s in seconds]
