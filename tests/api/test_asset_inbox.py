"""Seam 1 at fast depth: an approver rejects an asset with a comment, and it goes back to the
same writer Session; only that asset is redone and the run waits for approval again. The inbox's
listing, decisions, previews, redo and budget rules are proved below the API: see
tests/engine/test_inbox*.py."""

import json
from typing import Any

import httpx
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.conftest import SignIn
from tests.api.helpers import AWAITING, create_on, marketo_sends, read_events, until_status
from tests.harness.stack import Stack

DG_OWNER = "dg-owner@demo.example"
DG_APPROVER = "dg-approver@demo.example"
ASSETS = {"landing_page", "social", "one_pager", "email_writer", "design"}
PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
REDONE_PAGE = {**PAGE, "body": "Calmer words"}
COMMENT = "Drop the hype"


def waiting_default(owner: httpx.Client) -> str:
    campaign_id: str = create_on(owner, DEFAULT_WORKFLOW_NAME)["id"]
    until_status(owner, campaign_id, AWAITING)
    return campaign_id


def inbox(client: httpx.Client, campaign_id: str | None = None) -> list[dict[str, Any]]:
    response = client.get("/inbox")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return [i for i in items if campaign_id is None or i["campaign_id"] == campaign_id]


def decide(
    client: httpx.Client, campaign_id: str, asset: str, decision: str, comment: str = ""
) -> httpx.Response:
    return client.post(
        f"/campaigns/{campaign_id}/assets/{asset}/{decision}", json={"comment": comment}
    )


def outputs(client: httpx.Client, campaign_id: str) -> dict[str, dict[str, Any]]:
    rows = client.get(f"/campaigns/{campaign_id}/steps").json()
    return {r["step"]: r for r in rows}


def events_after_redo(api: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    """Every run event up to the run waiting for approval again after a rejection."""
    events = read_events(api, campaign_id)
    while not (
        any(e["status"] == "rejected" for e in events)
        and (events[-1]["step"], events[-1]["status"]) == ("run", AWAITING)
    ):
        events += read_events(api, campaign_id, last_event_id=events[-1]["seq"])
    return events


def test_reject_returns_to_the_same_writer_session_and_redoes_only_that_asset(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    campaign_id = waiting_default(owner)
    before = outputs(approver, campaign_id)
    assert decide(approver, campaign_id, "social", "approve", "Fine").status_code == 200
    seen = stack.agent.message_ids()
    stack.agent.script([json.dumps(REDONE_PAGE)])

    rejected = decide(approver, campaign_id, "landing_page", "reject", COMMENT)

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["decision"] == "rejected"
    until_status(owner, campaign_id, AWAITING)
    after = outputs(approver, campaign_id)
    assert after["landing_page"]["output"] == REDONE_PAGE
    assert after["landing_page"]["session"] == before["landing_page"]["session"]
    for untouched in set(before) - {"landing_page"}:
        assert after[untouched] == before[untouched], untouched
    calls = stack.agent.message_ids()[len(seen) :]
    # One writer call, to the same session, and the brand reviewer's check of the redo.
    assert all(c.startswith(before["landing_page"]["session"]) for c in calls)
    assert len([c for c in calls if ":review:" not in c]) == 1
    assert len([c for c in calls if ":review:" in c]) == 1
    events = events_after_redo(owner, campaign_id)
    rejection = [e for e in events if e["status"] == "rejected"]
    assert [(e["step"], e["reason"]) for e in rejection] == [("landing_page", COMMENT)]
    redone = [e for e in events if e["seq"] > rejection[0]["seq"] and e["session"]]
    assert {e["step"] for e in redone} == {"landing_page"}
    assert {e["session"] for e in redone} == {before["landing_page"]["session"]}
    assert marketo_sends(stack, campaign_id) == []
    assert {i["step"] for i in inbox(approver, campaign_id)} == ASSETS - {"social"}
