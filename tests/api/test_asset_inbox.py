"""Seam 1 at fast depth: the approval inbox. An approver sees the assets waiting for their
team, with each asset's preview and the brand reviewer's flags, and approves or rejects each
one with a comment. A rejection goes back to the same writer Session and only that asset is
redone; once every asset is approved the campaign sends."""

import json
import uuid
from html import escape
from typing import Any

import httpx
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.conftest import SignIn
from tests.api.helpers import (
    AWAITING,
    DRAFT_APPROVE_PUBLISH,
    SENT,
    create_on,
    edge,
    marketo_sends,
    read_events,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

DG_OWNER = "dg-owner@demo.example"
DG_APPROVER = "dg-approver@demo.example"
DG_VIEWER = "dg-viewer@demo.example"
DG_LEAD = "dg-lead@demo.example"
PM_OWNER = "pm-owner@demo.example"
PM_APPROVER = "pm-approver@demo.example"
ASSETS = {"landing_page", "social", "one_pager", "email_writer"}
PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
REDONE_PAGE = {**PAGE, "body": "Calmer words"}
FIX = {
    "verdict": "fix",
    "issues": [{"check": "banned_claim", "detail": "100% protection is a banned claim"}],
}
COMMENT = "Drop the hype"
PASS = {"verdict": "pass", "issues": []}
BUDGET_PAUSED = "budget_paused"
# 1000 input and 500 output tokens per reply cost $0.0105, past a $0.01 budget.
SPENT_AFTER_ONE_REPLY = "[agent:usage-1000-500]"


def reviewed_page_workflow(owner: httpx.Client) -> str:
    name = workflow_name("inbox-review")
    save_workflow(
        owner,
        name,
        {
            "steps": [step("landing_page", "agent", review_rounds=2), step("approval", "approval")],
            "edges": [edge("landing_page", "approval")],
        },
    )
    return name


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


def test_inbox_lists_waiting_assets_of_the_approvers_team_only(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    dg_id = waiting_default(sign_in(DG_OWNER))
    pm_id = waiting_default(sign_in(PM_OWNER))

    dg_items = inbox(sign_in(DG_APPROVER))
    pm_items = inbox(sign_in(PM_APPROVER))

    assert {i["step"] for i in dg_items if i["campaign_id"] == dg_id} == ASSETS
    assert {i["step"] for i in pm_items if i["campaign_id"] == pm_id} == ASSETS
    assert pm_id not in {i["campaign_id"] for i in dg_items}
    assert dg_id not in {i["campaign_id"] for i in pm_items}
    assert {i["team"] for i in dg_items} == {"demand-gen"}


def test_inbox_leaves_out_campaigns_still_drafting_and_the_approvers_own(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    lead = sign_in(DG_LEAD)
    own_id = waiting_default(lead)

    assert inbox(lead, own_id) == []
    assert {i["step"] for i in inbox(sign_in(DG_APPROVER), own_id)} == ASSETS


def test_inbox_is_for_approvers(stack: Stack, sign_in: SignIn) -> None:
    assert sign_in(DG_OWNER).get("/inbox").status_code == 403
    assert sign_in(DG_VIEWER).get("/inbox").status_code == 403
    assert sign_in(DG_APPROVER).get("/inbox").status_code == 200
    with httpx.Client(base_url=stack.api_url) as anonymous:
        assert anonymous.get("/inbox").status_code == 401


def test_each_asset_carries_its_preview_and_the_reviewers_flags(
    stack: Stack, sign_in: SignIn
) -> None:
    owner = sign_in(DG_OWNER)
    name = workflow_name("inbox")
    save_workflow(
        owner,
        name,
        {
            "steps": [step("landing_page", "agent", review_rounds=2), step("approval", "approval")],
            "edges": [edge("landing_page", "approval")],
        },
    )
    stack.agent.script([json.dumps(r) for r in (PAGE, FIX, PAGE, FIX, PAGE, FIX)])
    campaign_id = create_on(owner, name)["id"]
    until_status(owner, campaign_id, AWAITING)

    approver = sign_in(DG_APPROVER)
    [item] = inbox(approver, campaign_id)

    assert item["step"] == "landing_page"
    assert item["output"] == PAGE
    assert [f["check"] for f in item["flags"]] == ["banned_claim"]
    assert "banned claim" in item["flags"][0]["detail"]
    preview = approver.get(item["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    assert "H" in preview.text


def test_the_social_asset_previews_its_post_text(stack: Stack, sign_in: SignIn) -> None:
    stack.agent.script([])
    approver = sign_in(DG_APPROVER)
    campaign_id = waiting_default(sign_in(DG_OWNER))

    [item] = [i for i in inbox(approver, campaign_id) if i["step"] == "social"]

    assert item["preview_url"]
    preview = approver.get(item["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("text/html")
    for post in item["output"]["posts"]:
        assert escape(post["text"]) in preview.text


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


def test_approving_every_asset_sends_the_campaign(stack: Stack, sign_in: SignIn) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    campaign_id = waiting_default(owner)

    for asset in ("landing_page", "social", "one_pager"):
        assert decide(approver, campaign_id, asset, "approve").status_code == 200
        assert owner.get(f"/campaigns/{campaign_id}").json()["status"] == AWAITING
    assert marketo_sends(stack, campaign_id) == []
    assert decide(approver, campaign_id, "email_writer", "approve", "Ship it").status_code == 200

    sent = until_status(owner, campaign_id, SENT)
    assert sent["receipt"]
    assert len(marketo_sends(stack, campaign_id)) == 1


def test_a_redone_email_is_the_one_that_sends(stack: Stack, sign_in: SignIn) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    campaign_id = waiting_default(owner)
    redone = {"subject": "Redone", "preheader": "P", "body": "B", "call_to_action": "Go"}
    stack.agent.script([json.dumps(redone), json.dumps({**redone, "subject": "Redone B"})])

    assert decide(approver, campaign_id, "email_writer", "reject", COMMENT).status_code == 200
    until_status(owner, campaign_id, AWAITING)
    for asset in ASSETS:
        assert decide(approver, campaign_id, asset, "approve").status_code == 200

    sent = until_status(owner, campaign_id, SENT)
    assert sent["draft"]["subject"] == "Redone"
    assert marketo_sends(stack, campaign_id)[0]["variants"][0]["subject"] == "Redone"


def test_decisions_are_refused_without_a_comment_for_a_reject_and_for_the_wrong_person(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    campaign_id = waiting_default(owner)

    assert decide(approver, campaign_id, "social", "reject", "  ").status_code == 422
    assert decide(owner, campaign_id, "social", "approve").status_code == 403
    assert decide(sign_in(PM_APPROVER), campaign_id, "social", "approve").status_code == 404
    assert decide(approver, campaign_id, "strategist", "approve").status_code == 404
    assert decide(approver, str(uuid.uuid4()), "social", "approve").status_code == 404
    assert decide(approver, campaign_id, "social", "approve").status_code == 200
    assert decide(approver, campaign_id, "social", "approve").status_code == 409
    assert decide(approver, campaign_id, "social", "reject", COMMENT).status_code == 409
    lead = sign_in(DG_LEAD)
    own_id = waiting_default(lead)
    assert decide(lead, own_id, "social", "approve").status_code == 403


def test_a_decision_on_a_campaign_that_is_not_waiting_is_refused(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    name = workflow_name("inbox-pub")
    save_workflow(owner, name, DRAFT_APPROVE_PUBLISH)
    campaign_id = create_on(owner, name)["id"]
    until_status(owner, campaign_id, AWAITING)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(owner, campaign_id, SENT)

    assert decide(approver, campaign_id, "draft", "approve").status_code == 409


def test_a_redone_asset_goes_through_the_brand_reviewer_again(
    stack: Stack, sign_in: SignIn
) -> None:
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    stack.agent.script([json.dumps(r) for r in (PAGE, FIX, PAGE, FIX, PAGE, FIX)])
    campaign_id = create_on(owner, reviewed_page_workflow(owner))["id"]
    until_status(owner, campaign_id, AWAITING)
    assert [f["check"] for f in inbox(approver, campaign_id)[0]["flags"]] == ["banned_claim"]
    seen = len(stack.agent.message_ids())
    fixed = {**PAGE, "body": "Calm and checked"}
    # The redo, the reviewer's fix, the writer's fix, and the reviewer's pass.
    stack.agent.script([json.dumps(r) for r in (REDONE_PAGE, FIX, fixed, PASS)])

    assert decide(approver, campaign_id, "landing_page", "reject", COMMENT).status_code == 200

    until_status(owner, campaign_id, AWAITING)
    [item] = inbox(approver, campaign_id)
    assert item["output"] == fixed
    assert item["flags"] == []
    assert len(stack.agent.message_ids()) - seen == 4


def test_a_redo_stops_at_the_budget_until_the_owner_raises_it(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    owner, approver = sign_in(DG_OWNER), sign_in(DG_APPROVER)
    name = workflow_name("inbox-budget")
    save_workflow(
        owner,
        name,
        {
            "steps": [step("landing_page", "agent"), step("approval", "approval")],
            "edges": [edge("landing_page", "approval")],
        },
    )
    created = owner.post(
        "/campaigns",
        json={
            "report": f"{SPENT_AFTER_ONE_REPLY}\nVolt Typhoon",
            "workflow": name,
            "budget_usd": 0.01,
        },
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    until_status(owner, campaign_id, AWAITING)
    seen = len(stack.agent.message_ids())
    stack.agent.script([json.dumps(REDONE_PAGE)])

    assert decide(approver, campaign_id, "landing_page", "reject", COMMENT).status_code == 200

    until_status(owner, campaign_id, BUDGET_PAUSED)
    assert len(stack.agent.message_ids()) == seen
    raised = owner.post(f"/campaigns/{campaign_id}/budget", json={"budget_usd": 1})
    assert raised.status_code == 200, raised.text
    until_status(owner, campaign_id, AWAITING)
    assert len(stack.agent.message_ids()) - seen == 1
    assert inbox(approver, campaign_id)[0]["output"] == REDONE_PAGE
