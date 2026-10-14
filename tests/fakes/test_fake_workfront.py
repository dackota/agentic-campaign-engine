"""The fake Workfront, in process: it speaks OAuth2 client credentials and holds projects,
tasks, and approvals. One approval creates one task for the campaign, and the receipt links to
it. The worker's own Workfront adapter drives it through an ASGI transport. A task status
change posts a signed event that verifies with the Campaign API's webhook rules."""

import asyncio
import json
import threading
import time
from typing import Any

import httpx
import pytest
from ace_engine import webhooks
from campaign_api.webhook_routes import WORKFRONT_HEADERS
from campaign_worker.publisher import ApprovedCampaign, Receipt
from campaign_worker.workfront import WorkfrontAdapter
from fake_workfront import app as fake_workfront
from fake_workfront.app import WorkfrontConfig
from fastapi.testclient import TestClient

from tests.support.dag import GOOD_DRAFT
from tests.support.settings import unit_settings

CLIENT_ID = "workfront-id"
CLIENT_SECRET = "workfront-secret"
WEBHOOK_SECRET = "workfront-webhook-secret"
BASE_URL = "http://workfront.test"
CAMPAIGN_ID = "11111111-2222-3333-4444-555555555555"
STEP_KEY = f"campaign-{CAMPAIGN_ID}:publish"
CONFIG = WorkfrontConfig(CLIENT_ID, CLIENT_SECRET, "http://127.0.0.1:9/dead", WEBHOOK_SECRET)
SETTINGS = unit_settings(
    workfront_url=BASE_URL,
    workfront_client_id=CLIENT_ID,
    workfront_client_secret=CLIENT_SECRET,
    workfront_webhook_secret=WEBHOOK_SECRET,
)
APPROVED = ApprovedCampaign(CAMPAIGN_ID, (GOOD_DRAFT, GOOD_DRAFT), STEP_KEY)
API = "/attask/api/v15.0"
POST_WAIT_SECONDS = 5
POLL_SECONDS = 0.01


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The status events the fake would post to its webhook: no thread dials out."""
    seen: list[dict[str, Any]] = []
    lock = threading.Lock()

    def record(_config: WorkfrontConfig, event: dict[str, Any]) -> None:
        with lock:
            seen.append(event)

    monkeypatch.setattr(fake_workfront, "_post_event", record)
    return seen


@pytest.fixture
def workfront(posted: list[dict[str, Any]]) -> TestClient:
    return TestClient(fake_workfront.create_app(CONFIG))


def _token(
    client: TestClient, client_id: str = CLIENT_ID, secret: str = CLIENT_SECRET
) -> httpx.Response:
    response: httpx.Response = client.post(
        "/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
    )
    return response


def _signed_in(client: TestClient) -> TestClient:
    token = _token(client).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _publish(client: TestClient) -> Receipt:
    async def publish() -> Receipt:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport) as http:
            return await WorkfrontAdapter(SETTINGS).publish(http, APPROVED, STEP_KEY)

    return asyncio.run(publish())


def _until_posted(seen: list[dict[str, Any]], count: int) -> None:
    """Wait for the fake's background thread to post `count` events."""
    deadline = time.monotonic() + POST_WAIT_SECONDS
    while len(seen) < count and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)


def test_token_route_issues_a_token_for_good_client_credentials(workfront: TestClient) -> None:
    response = _token(workfront)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] > 0


def test_token_route_rejects_bad_client_credentials(workfront: TestClient) -> None:
    wrong_secret = _token(workfront, secret="nope")
    wrong_client = _token(workfront, client_id="someone-else")

    assert wrong_secret.status_code == 401
    assert wrong_client.status_code == 401
    assert "access_token" not in wrong_secret.text


@pytest.mark.parametrize("path", ["/proj/search", "/task/search", "/appr/search"])
def test_rest_reads_without_a_token_are_401(workfront: TestClient, path: str) -> None:
    assert workfront.get(f"{API}{path}").status_code == 401
    bad = workfront.get(f"{API}{path}", headers={"Authorization": "Bearer made-up"})
    assert bad.status_code == 401


def test_rest_writes_without_a_token_are_401(workfront: TestClient) -> None:
    assert workfront.post(f"{API}/task", json={"name": "x"}).status_code == 401


def test_fake_holds_a_project_a_task_and_an_approval(workfront: TestClient) -> None:
    client = _signed_in(workfront)
    project = client.post(f"{API}/proj", json={"name": "Q4", "externalID": "proj-1"}).json()["data"]
    again = client.post(f"{API}/proj", json={"name": "Q4", "externalID": "proj-1"}).json()["data"]
    body = {"name": "Launch", "projectID": project["ID"], "externalID": "task-1"}
    task = client.post(f"{API}/task", json=body).json()["data"]
    renamed = client.post(f"{API}/task", json={**body, "name": "Launch v2"}).json()["data"]
    approval = client.post(f"{API}/appr", json={"taskID": task["ID"]}).json()["data"]
    found = client.get(f"{API}/task/search", params={"externalID": "task-1"}).json()["data"]
    approvals = client.get(f"{API}/appr/search", params={"taskID": task["ID"]}).json()["data"]

    assert again["ID"] == project["ID"]
    assert renamed["ID"] == task["ID"]
    assert [t["name"] for t in found] == ["Launch v2"]
    assert found[0]["projectID"] == project["ID"]
    assert [a["ID"] for a in approvals] == [approval["ID"]]
    assert approvals[0]["status"] == "PENDING"


def test_approval_creates_one_task_and_the_receipt_links_to_it(workfront: TestClient) -> None:
    receipt = _publish(workfront)
    again = _publish(workfront)

    client = _signed_in(workfront)
    [task] = client.get(f"{API}/task/search", params={"externalID": CAMPAIGN_ID}).json()["data"]
    approvals = client.get(f"{API}/appr/search", params={"taskID": task["ID"]}).json()["data"]
    assert receipt.target == "workfront"
    assert receipt.receipt_id == task["ID"]
    assert receipt.url.startswith(BASE_URL)
    assert task["ID"] in receipt.url
    assert client.get(f"{API}/task/{task['ID']}").json()["data"]["ID"] == task["ID"]
    assert len(approvals) == 1
    # A retried publish updates the same task and makes no second one.
    assert again == receipt


def test_a_task_status_change_posts_one_event_naming_the_campaign(
    workfront: TestClient, posted: list[dict[str, Any]]
) -> None:
    receipt = _publish(workfront)
    client = _signed_in(workfront)

    client.put(f"{API}/task/{receipt.receipt_id}", json={"status": "INP"})
    client.put(f"{API}/task/{receipt.receipt_id}", json={"status": "INP"})
    client.put(f"{API}/task/{receipt.receipt_id}", json={"status": "CPL"})
    _until_posted(posted, 2)

    assert [(e["campaignId"], e["taskID"], e["status"]) for e in posted] == [
        (CAMPAIGN_ID, receipt.receipt_id, "INP"),
        (CAMPAIGN_ID, receipt.receipt_id, "CPL"),
    ]


def test_the_events_the_fake_posts_verify_with_the_campaign_apis_webhook_rules(
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
    event = {"id": "e1", "taskID": "t1", "campaignId": CAMPAIGN_ID, "status": "CPL"}

    fake_workfront._post_event(CONFIG, event)

    [request] = captured
    assert json.loads(request.content) == event
    webhooks.verify(request.headers, request.content, WEBHOOK_SECRET, names=WORKFRONT_HEADERS)
    with pytest.raises(webhooks.WebhookRejected):
        webhooks.verify(request.headers, request.content, "another", names=WORKFRONT_HEADERS)
    # Marketo's header names are not Workfront's.
    with pytest.raises(webhooks.WebhookRejected):
        webhooks.verify(request.headers, request.content, WEBHOOK_SECRET)
