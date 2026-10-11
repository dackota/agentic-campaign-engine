"""Seam 1 at fast depth: Slack and Google Docs are on by flag. With their tokens set and
local stand-ins for both APIs, the approval request and the publish notice reach Slack and
one Google Doc holds the brief and the drafts. With no tokens, a campaign still runs to
approval and publish and nothing errors."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.api.helpers import APPROVER, AWAITING, OWNER, REPORT, SENT, create, settle, until_status
from tests.harness.stack import Stack

HTTP_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def wired() -> Iterator[Stack]:
    """A stack with Slack and Google switched on, pointed at local stand-ins."""
    with Stack(integrations=True) as running:
        yield running


def client(stack: Stack, email: str) -> httpx.Client:
    return httpx.Client(
        base_url=stack.api_url,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {stack.dex.token(email)}"},
    )


def read(url: str) -> list[dict[str, Any]]:
    response = httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def run_to_sent(stack: Stack, report: str) -> dict[str, Any]:
    stack.agent.script([])
    with client(stack, OWNER) as owner, client(stack, APPROVER) as approver:
        campaign_id = create(owner, report)["id"]
        assert settle(owner, campaign_id)["status"] == AWAITING
        assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
        return until_status(owner, campaign_id, SENT)


def test_slack_gets_the_approval_request_and_the_publish_notice(wired: Stack) -> None:
    report = f"{REPORT} slack-marker-1"
    sent = run_to_sent(wired, report)

    texts = [m["text"] for m in read(wired.slack_messages_url) if sent["id"] in m["text"]]

    assert len(texts) == 2, texts
    assert "approval" in texts[0].lower()
    assert "sent" in texts[1].lower() or "published" in texts[1].lower()
    assert sent["receipt"] in texts[1]
    channels = {m["channel"] for m in read(wired.slack_messages_url) if sent["id"] in m["text"]}
    assert channels == {wired.slack_channel}
    assert wired.slack_token not in str(read(wired.slack_messages_url))


def test_google_stand_in_gets_one_doc_with_the_brief_and_drafts(wired: Stack) -> None:
    report = f"{REPORT} google-marker-2"
    sent = run_to_sent(wired, report)

    docs = [d for d in read(wired.google_documents_url) if report in d["text"]]

    assert len(docs) == 1, docs
    assert sent["draft"]["subject"] in docs[0]["text"]
    assert sent["variant_b"]["subject"] in docs[0]["text"]


def test_features_off_runs_to_sent_without_error(stack: Stack, api: httpx.Client) -> None:
    assert stack.integrations is False
    campaign_id = create(api)["id"]
    assert settle(api, campaign_id)["status"] == AWAITING

    approved = client(stack, APPROVER)
    assert approved.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    approved.close()

    assert until_status(api, campaign_id, SENT)["receipt"]
