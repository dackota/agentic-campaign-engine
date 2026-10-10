"""Seam 1 at fast depth: the Campaign API over HTTP, with real Postgres, Temporal's
time-skipping test server, and the scripted A2A agent behind it."""

import json
import uuid
from pathlib import Path

import httpx
import jsonschema

from tests.api.helpers import GOOD_DRAFT, REPORT, create, settle
from tests.harness.stack import Stack

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "apps/engine/ace_engine/email_draft.schema.json"


def test_created_campaign_is_returned_with_its_draft(api: httpx.Client) -> None:
    created = create(api)
    assert created["report"] == REPORT

    campaign = settle(api, created["id"])

    assert campaign["status"] == "awaiting_approval"
    assert campaign["draft"]["subject"]
    assert "Volt Typhoon" in campaign["draft"]["body"]


def test_draft_matches_email_contract_schema(api: httpx.Client) -> None:
    campaign = settle(api, create(api)["id"])

    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(campaign["draft"], schema)


def test_agent_reply_breaking_contract_fails_campaign_without_draft(
    stack: Stack, api: httpx.Client
) -> None:
    stack.agent.script(["not json at all", json.dumps({"subject": "only a subject"})])

    campaign = settle(api, create(api)["id"])

    assert campaign["status"] == "failed"
    assert campaign["draft"] is None
    assert "contract" in campaign["failure_reason"]


def test_one_repair_attempt_recovers_a_bad_first_reply(stack: Stack, api: httpx.Client) -> None:
    stack.agent.script([json.dumps({"subject": "missing fields"}), json.dumps(GOOD_DRAFT)])

    campaign = settle(api, create(api)["id"])

    assert campaign["status"] == "awaiting_approval"
    assert campaign["draft"] == GOOD_DRAFT


def test_rejects_empty_report(api: httpx.Client) -> None:
    for report in ("", "   \n"):
        assert api.post("/campaigns", json={"report": report}).status_code == 422


def test_unknown_campaign_is_404(api: httpx.Client) -> None:
    assert api.get(f"/campaigns/{uuid.uuid4()}").status_code == 404
