"""Seam 1 at fast depth: the email preview route returns the rendered email."""

import re
import uuid
from pathlib import Path

import httpx

from tests.api.helpers import AWAITING, create, settle
from tests.harness.stack import Stack

SNAPSHOT = Path(__file__).parent / "snapshots" / "email_preview.html"
MAX_BYTES = 100_000


def _preview(api: httpx.Client, campaign_id: str) -> httpx.Response:
    return api.get(f"/campaigns/{campaign_id}/preview")


def test_preview_returns_rendered_email(api: httpx.Client) -> None:
    campaign = settle(api, create(api)["id"])
    assert campaign["status"] == AWAITING

    response = _preview(api, campaign["id"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert campaign["draft"]["subject"] in response.text
    assert 'style="' in response.text
    images = re.findall(r"<img\b[^>]*>", response.text)
    assert images
    assert all(re.search(r'alt="[^"]+"', tag) for tag in images)
    assert len(response.content) < MAX_BYTES


def test_second_get_returns_same_bytes(api: httpx.Client) -> None:
    campaign = settle(api, create(api)["id"])

    assert _preview(api, campaign["id"]).content == _preview(api, campaign["id"]).content


def test_preview_matches_snapshot(api: httpx.Client) -> None:
    campaign = settle(api, create(api)["id"])

    assert _preview(api, campaign["id"]).text == SNAPSHOT.read_text()


def test_preview_404_unknown_campaign(api: httpx.Client) -> None:
    assert _preview(api, str(uuid.uuid4())).status_code == 404


def test_preview_409_when_run_has_no_draft(stack: Stack, api: httpx.Client) -> None:
    stack.agent.script(["not json at all", "still not json"])
    campaign = settle(api, create(api)["id"])
    assert campaign["draft"] is None

    assert _preview(api, campaign["id"]).status_code == 409
