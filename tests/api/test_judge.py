"""Seam 1 at fast depth, with the scripted judge: a judge step scores every asset against the
written rubric, stores score and reason in the run events and shows them on the run and in the
approval inbox. A score below the floor ends the run failed with the reason; others go on."""

import json
from typing import Any

import httpx
from ace_engine import judge
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.conftest import SignIn
from tests.api.helpers import (
    AWAITING,
    FAILED,
    FINISHED,
    create_on,
    edge,
    read_events,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."


def judged_workflow(api: httpx.Client) -> str:
    name = workflow_name("judged")
    save_workflow(
        api,
        name,
        {
            "steps": [
                step("landing_page", "agent"),
                step("social", "agent"),
                step("judge", "agent"),
            ],
            "edges": [edge("landing_page", "judge"), edge("social", "judge")],
        },
    )
    return name


def scored(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["step"]: json.loads(e["reason"]) for e in events if e["status"] == "scored"}


def test_every_asset_gets_a_score_and_reason_in_events_and_on_the_asset(
    api: httpx.Client, stack: Stack
) -> None:
    stack.agent.script([])
    created = create_on(api, judged_workflow(api), REPORT)

    done = until_status(api, created["id"], FINISHED, FAILED)

    assert done["status"] == FINISHED, done
    in_events = scored(read_events(api, created["id"]))
    assert set(in_events) == {"landing_page", "social"}
    for entry in in_events.values():
        assert judge.MIN_SCORE <= entry["score"] <= judge.MAX_SCORE and entry["reason"].strip()
    assert {s["step"]: (s["score"], s["reason"]) for s in done["scores"]} == {
        step_id: (e["score"], e["reason"]) for step_id, e in in_events.items()
    }


def test_the_judge_is_sent_the_rubric_and_the_assets(api: httpx.Client, stack: Stack) -> None:
    stack.agent.script([])
    created = create_on(api, judged_workflow(api), REPORT)
    until_status(api, created["id"], FINISHED, FAILED)

    sent = next(
        m for m in stack.agent.messages() if "OUTPUT OF landing_page" in m and "rubric" in m.lower()
    )

    assert judge.RUBRIC_PATH.read_text().splitlines()[0] in sent
    assert "OUTPUT OF social" in sent


def run_with_judge_reply(api: httpx.Client, stack: Stack, landing_score: int) -> dict[str, Any]:
    name = workflow_name("floor")
    save_workflow(
        api,
        name,
        {
            "steps": [step("landing_page", "agent"), step("judge", "agent")],
            "edges": [edge("landing_page", "judge")],
        },
    )
    verdict = {"scores": [{"step": "landing_page", "score": landing_score, "reason": "Too vague"}]}
    stack.agent.script([json.dumps(PAGE), json.dumps(verdict)])
    return until_status(api, create_on(api, name, REPORT)["id"], FINISHED, FAILED)


def test_score_below_floor_fails_the_run_with_the_reason(api: httpx.Client, stack: Stack) -> None:
    done = run_with_judge_reply(api, stack, judge.FLOOR - 1)

    assert done["status"] == FAILED
    assert "landing_page" in done["failure_reason"] and "Too vague" in done["failure_reason"]
    assert [s["score"] for s in done["scores"]] == [judge.FLOOR - 1]


def test_scores_at_or_above_floor_let_the_run_go_on(api: httpx.Client, stack: Stack) -> None:
    at_floor = run_with_judge_reply(api, stack, judge.FLOOR)
    top = run_with_judge_reply(api, stack, judge.MAX_SCORE)

    assert at_floor["status"] == FINISHED and top["status"] == FINISHED


def test_a_planted_low_score_blocks_the_default_workflow(api: httpx.Client, stack: Stack) -> None:
    stack.agent.script([])
    created = create_on(api, DEFAULT_WORKFLOW_NAME, f"{REPORT}\n[agent:low-score]")

    done = until_status(api, created["id"], FAILED, AWAITING)

    assert done["status"] == FAILED
    assert "below the floor" in done["failure_reason"]


def test_run_and_inbox_carry_score_and_reason(stack: Stack, sign_in: SignIn) -> None:
    stack.agent.script([])
    owner = sign_in("dg-owner@demo.example")
    created = create_on(owner, DEFAULT_WORKFLOW_NAME, REPORT)
    run = until_status(owner, created["id"], AWAITING, FAILED)

    items = [
        i
        for i in sign_in("dg-approver@demo.example").get("/inbox").json()
        if i["campaign_id"] == created["id"]
    ]

    assert run["status"] == AWAITING
    assert {i["step"] for i in items} == {s["step"] for s in run["scores"]}
    assert "judge" not in {i["step"] for i in items}
    for item in items:
        assert judge.MIN_SCORE <= item["score"] <= judge.MAX_SCORE
        assert item["score_reason"].strip()


def test_a_campaign_with_no_workflow_gets_a_score_in_events_and_inbox(
    stack: Stack, sign_in: SignIn
) -> None:
    stack.agent.script([])
    owner = sign_in("dg-owner@demo.example")
    response = owner.post("/campaigns", json={"report": REPORT})
    assert response.status_code == 201, response.text
    campaign_id = response.json()["id"]

    run = until_status(owner, campaign_id, AWAITING, FAILED)

    assert run["status"] == AWAITING, run
    assert set(scored(read_events(owner, campaign_id))) == {"email_draft"}
    items = [
        i
        for i in sign_in("dg-approver@demo.example").get("/inbox").json()
        if i["campaign_id"] == campaign_id
    ]
    assert [i["step"] for i in items] == ["email_draft"]
    assert items[0]["score"] is not None and items[0]["score_reason"].strip()
