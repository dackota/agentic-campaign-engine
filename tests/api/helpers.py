"""Helpers the Campaign API tests share: make a campaign, wait for it to reach a status."""

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any
from xml.etree import ElementTree

import httpx

from tests.harness.stack import Stack

REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."
GOOD_DRAFT = {
    "subject": "Patch your VPN today",
    "preheader": "Attackers are scanning for it",
    "body": "Hello, apply the fix now.",
    "call_to_action": "Patch now",
}
AWAITING = "awaiting_approval"
FAILED = "failed"
SENT = "sent"
FINISHED = "finished"
RETRYING = "retrying"
# Demo users from platform/dex/config.yaml.
OWNER = "dg-owner@demo.example"
APPROVER = "dg-approver@demo.example"
LIVE_POLL_SECONDS = 300  # a real model takes seconds per reply, and the default workflow asks six
POLL_SECONDS = LIVE_POLL_SECONDS if os.environ.get("ACE_DEPTH") == "live" else 30
POLL_INTERVAL_SECONDS = 0.2
STREAM_TIMEOUT_SECONDS = 30


def create(api: httpx.Client, report: str = REPORT) -> dict[str, Any]:
    response = api.post("/campaigns", json={"report": report})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def until_status(api: httpx.Client, campaign_id: str, *wanted: str) -> dict[str, Any]:
    """Poll the campaign until its status is one of `wanted`; return it."""
    deadline = time.monotonic() + POLL_SECONDS
    campaign: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = api.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 200, response.text
        campaign = response.json()
        if campaign["status"] in wanted:
            return campaign
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"campaign never reached {' or '.join(wanted)}; last: {campaign}")


def settle(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Wait until drafting ends: the run waits for approval or has failed."""
    return until_status(api, campaign_id, AWAITING, FAILED)


def retry_step(api: httpx.Client, campaign_id: str) -> httpx.Response:
    """Ask the run to retry the step that stopped it: the app's retry-step action."""
    return api.post(f"/campaigns/{campaign_id}/retry")


def workflow_name(prefix: str = "wf") -> str:
    """A fresh workflow name: the stack is shared by tests, so names must not collide."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def save_workflow(api: httpx.Client, name: str, dag: dict[str, Any]) -> dict[str, Any]:
    response = api.post(f"/workflows/{name}/versions", json=dag)
    assert response.status_code == 201, response.text
    saved: dict[str, Any] = response.json()
    return saved


def create_on(api: httpx.Client, workflow: str, report: str = REPORT) -> dict[str, Any]:
    response = api.post("/campaigns", json={"report": report, "workflow": workflow})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def step(step_id: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {"id": step_id, "kind": kind, **extra}


def edge(source: str, target: str) -> dict[str, str]:
    return {"from": source, "to": target}


# The smallest workflow that drafts, waits for a human, then publishes.
DRAFT_APPROVE_PUBLISH = {
    "steps": [step("draft", "agent"), step("approve", "approval"), step("publish", "publish")],
    "edges": [edge("draft", "approve"), edge("approve", "publish")],
}


def read_events(
    api: httpx.Client,
    campaign_id: str,
    last_event_id: int | None = None,
    after: int | None = None,
) -> list[dict[str, Any]]:
    """Read the run event stream until the server closes it; one dict per event. `after`
    starts it the way the browser does, from the query instead of Last-Event-ID."""
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    params = {"after": str(after)} if after is not None else {}
    events: list[dict[str, Any]] = []
    with api.stream(
        "GET",
        f"/campaigns/{campaign_id}/events",
        headers=headers,
        params=params,
        timeout=STREAM_TIMEOUT_SECONDS,
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


# The fake Marketo, read from the outside through its own REST API.
MARKETO_TOKEN_PATH = "/identity/oauth/token"
MARKETO_PROGRAMS_PATH = "/rest/asset/v1/programs.json"
MARKETO_HTTP_TIMEOUT_SECONDS = 10
# Activity webhooks: the HMAC-SHA256 of "<timestamp>." + body, hex, in this header.
MARKETO_WEBHOOK_PATH = "/webhooks/marketo"
SIGNATURE_HEADER = "X-Marketo-Signature"
TIMESTAMP_HEADER = "X-Marketo-Timestamp"


def marketo_token(marketo_url: str, client_id: str, client_secret: str) -> httpx.Response:
    return httpx.post(
        f"{marketo_url}{MARKETO_TOKEN_PATH}",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )


def marketo_programs(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """The programs the fake Marketo holds for this campaign, each with its sends."""
    token = marketo_token(stack.marketo_url, stack.marketo_client_id, stack.marketo_client_secret)
    assert token.status_code == 200, token.text
    response = httpx.get(
        f"{stack.marketo_url}{MARKETO_PROGRAMS_PATH}",
        params={"externalId": campaign_id},
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    programs: list[dict[str, Any]] = body["result"]
    return programs


def marketo_sends(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """Every send the fake Marketo made for this campaign, across its programs."""
    return [send for p in marketo_programs(stack, campaign_id) for send in p["sends"]]


def signed_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Headers that sign `body` the way the fake Marketo signs its activity webhooks."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {
        TIMESTAMP_HEADER: stamp,
        SIGNATURE_HEADER: f"sha256={digest.hexdigest()}",
        "Content-Type": "application/json",
    }


def events_until(api: httpx.Client, campaign_id: str, final_status: str) -> list[dict[str, Any]]:
    """Every run event up to the run event `final_status`. The stream closes at each final
    state (waiting for approval, failed), so read on from the last event until it comes."""
    events = read_events(api, campaign_id)
    while (events[-1]["step"], events[-1]["status"]) != ("run", final_status):
        events += read_events(api, campaign_id, last_event_id=events[-1]["seq"])
    return events


# The fake CMS and the fake S3 store, read from the outside through their own REST APIs.
CONTENT_HTTP_TIMEOUT_SECONDS = 10
CMS_PAGES_PATH = "/api/pages"
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def cms_pages(stack: Stack) -> list[dict[str, Any]]:
    response = httpx.get(f"{stack.cms_url}{CMS_PAGES_PATH}", timeout=CONTENT_HTTP_TIMEOUT_SECONDS)
    assert response.status_code == 200, response.text
    pages: list[dict[str, Any]] = response.json()["data"]
    return pages


def cms_page(stack: Stack, campaign_id: str) -> dict[str, Any]:
    """The campaign's landing page, read back through the CMS's own API."""
    response = httpx.get(
        f"{stack.cms_url}{CMS_PAGES_PATH}/{campaign_id}", timeout=CONTENT_HTTP_TIMEOUT_SECONDS
    )
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()["data"]
    return page


def bucket_keys(stack: Stack, prefix: str = "") -> list[str]:
    """The object keys in the bucket under `prefix`, listed through S3's ListObjectsV2."""
    response = httpx.get(
        f"{stack.s3_url}/{stack.s3_bucket}",
        params={"list-type": "2", "prefix": prefix},
        timeout=CONTENT_HTTP_TIMEOUT_SECONDS,
    )
    assert response.status_code == 200, response.text
    root = ElementTree.fromstring(response.text)
    return [k.text or "" for k in root.iter(f"{S3_NAMESPACE}Key")]


def receipts(api: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    response = api.get(f"/campaigns/{campaign_id}")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["receipts"]
    return items


# The fake Workfront, read from the outside through its own REST API.
WORKFRONT_TOKEN_PATH = "/oauth2/token"
WORKFRONT_API = "/attask/api/v15.0"
WORKFRONT_WEBHOOK_PATH = "/webhooks/workfront"
WORKFRONT_SIGNATURE_HEADER = "X-Workfront-Signature"
WORKFRONT_TIMESTAMP_HEADER = "X-Workfront-Timestamp"
WORKFRONT_TARGET = "workfront"


def workfront_token(url: str, client_id: str, client_secret: str) -> httpx.Response:
    return httpx.post(
        f"{url}{WORKFRONT_TOKEN_PATH}",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )


def workfront_client(stack: Stack) -> httpx.Client:
    """A client for the fake Workfront that carries a fresh bearer token."""
    token = workfront_token(
        stack.workfront_url, stack.workfront_client_id, stack.workfront_client_secret
    )
    assert token.status_code == 200, token.text
    return httpx.Client(
        base_url=f"{stack.workfront_url}{WORKFRONT_API}",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=MARKETO_HTTP_TIMEOUT_SECONDS,
    )


def workfront_tasks(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    """The tasks the fake Workfront holds for this campaign."""
    with workfront_client(stack) as client:
        response = client.get("/task/search", params={"externalID": campaign_id})
    assert response.status_code == 200, response.text
    tasks: list[dict[str, Any]] = response.json()["data"]
    return tasks


def workfront_signed_headers(
    secret: str, body: bytes, timestamp: int | None = None
) -> dict[str, str]:
    """Headers that sign `body` the way the fake Workfront signs its status webhooks."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {
        WORKFRONT_TIMESTAMP_HEADER: stamp,
        WORKFRONT_SIGNATURE_HEADER: f"sha256={digest.hexdigest()}",
        "Content-Type": "application/json",
    }


DAY_SPEED = 100_000.0  # simulated audience seconds per real second: days in seconds


def send_campaign(api: httpx.Client, approver: httpx.Client) -> str:
    """Create a campaign, let it draft, approve it, and wait until it is sent."""
    campaign_id: str = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)
    return campaign_id
