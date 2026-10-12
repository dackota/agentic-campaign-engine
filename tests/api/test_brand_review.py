"""Seam 1 at fast depth, with a scripted brand reviewer: a writer step with review rounds
sends its draft to the reviewer, takes fixes back in the same Session, and after 2 rounds
flags what is still wrong for a human."""

import json
from typing import Any

import httpx

from tests.api.helpers import (
    FINISHED,
    create_on,
    read_events,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
PASS = {"verdict": "pass", "issues": []}
FIX = {
    "verdict": "fix",
    "issues": [{"check": "banned_claim", "detail": "100% protection is a banned claim"}],
}
WRITER = "landing_page"


def reply(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def run(api: httpx.Client, stack: Stack, replies: list[dict[str, Any]]) -> dict[str, Any]:
    name = workflow_name()
    save_workflow(
        api,
        name,
        {"steps": [step(WRITER, "agent", review_rounds=2)], "edges": []},
    )
    stack.agent.script([reply(r) for r in replies])
    campaign_id = create_on(api, name)["id"]
    return until_status(api, campaign_id, FINISHED)


def review_events(api: httpx.Client, campaign_id: str, status: str) -> list[dict[str, Any]]:
    return [e for e in read_events(api, campaign_id) if e["status"] == status]


def test_passing_draft_shows_no_flags(api: httpx.Client, stack: Stack) -> None:
    done = run(api, stack, [PAGE, PASS])

    assert done["flags"] == []
    assert review_events(api, done["id"], "review_fix") == []
    assert review_events(api, done["id"], "flagged") == []


def test_fix_then_pass_sends_one_fix_to_the_same_writer_session(
    api: httpx.Client, stack: Stack
) -> None:
    fixed = {**PAGE, "body": "Better"}

    done = run(api, stack, [PAGE, FIX, fixed, PASS])

    fixes = review_events(api, done["id"], "review_fix")
    outputs = api.get(f"/campaigns/{done['id']}/steps").json()
    writer = next(o for o in outputs if o["step"] == WRITER)
    assert len(fixes) == 1
    assert fixes[0]["step"] == WRITER and fixes[0]["session"] == writer["session"]
    assert "banned claim" in fixes[0]["reason"]
    assert writer["output"]["body"] == "Better"
    assert done["flags"] == []
    ids = [
        i
        for i in stack.agent.message_ids()
        if i.startswith(writer["session"]) and ":review" not in i
    ]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_draft_that_never_passes_stops_after_two_rounds_and_is_flagged(
    api: httpx.Client, stack: Stack
) -> None:
    done = run(api, stack, [PAGE, FIX, PAGE, FIX, PAGE, FIX])

    events = read_events(api, done["id"])
    flagged = [e for e in events if e["status"] == "flagged"]
    assert len([e for e in events if e["status"] == "review_fix"]) == 2
    assert len(flagged) == 1 and flagged[0]["step"] == WRITER
    assert "banned claim" in flagged[0]["reason"]
    assert len(done["flags"]) == 1
    assert done["flags"][0]["step"] == WRITER
    assert done["flags"][0]["issues"][0]["check"] == "banned_claim"
