"""Seam 1 at fast depth: the seeded default workflow, "Threat report to campaign". A
strategist and a research agent run first, then four writers at the same time."""

from typing import Any

import httpx
import jsonschema
import pytest
from ace_engine.agent_roles import ROLES
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.helpers import AWAITING, create_on, read_events, until_status

WRITERS = ["email_writer", "landing_page", "social", "one_pager"]
REPORT = (
    "Volt Typhoon targets edge routers\n"
    "Actors exploit unpatched VPN appliances.\n"
    "\n"
    "They stay hidden for months using living-off-the-land tools.\n"
    "Patching and credential rotation stop the known intrusion path."
)


@pytest.fixture
def run(api: httpx.Client) -> dict[str, Any]:
    """Start a campaign on the default workflow and read its stream to the approval wait."""
    campaign = create_on(api, DEFAULT_WORKFLOW_NAME, REPORT)
    events = read_events(api, campaign["id"])
    assert events[-1]["status"] == AWAITING, events
    steps = api.get(f"/campaigns/{campaign['id']}/steps")
    assert steps.status_code == 200, steps.text
    return {"campaign": campaign, "events": events, "steps": {s["step"]: s for s in steps.json()}}


def test_default_workflow_is_seeded_and_valid(api: httpx.Client) -> None:
    response = api.get(f"/workflows/{DEFAULT_WORKFLOW_NAME}/versions/2")

    assert response.status_code == 200, response.text
    ids = [s["id"] for s in response.json()["dag"]["steps"]]
    assert ids[:2] == ["strategist", "research"]
    assert set(ids) >= set(WRITERS)


def test_all_four_writers_start_before_any_finishes(run: dict[str, Any]) -> None:
    events = run["events"]
    started = {e["step"]: e["seq"] for e in events if e["status"] == "started"}
    finished = {e["step"]: e["seq"] for e in events if e["status"] == "succeeded"}

    assert set(WRITERS) <= started.keys()
    assert max(started[w] for w in WRITERS) < min(finished[w] for w in WRITERS)
    assert finished["research"] < min(started[w] for w in WRITERS)


def test_every_step_event_names_its_own_session(run: dict[str, Any]) -> None:
    # A score is the judge's note on an asset, so it names no session of its own.
    step_events = [e for e in run["events"] if e["step"] != "run" and e["status"] != "scored"]
    by_step: dict[str, set[str]] = {}
    for e in step_events:
        assert e["session"], e
        by_step.setdefault(e["step"], set()).add(e["session"])

    assert len(by_step) == 8
    assert all(len(ids) == 1 for ids in by_step.values())
    all_ids = [next(iter(ids)) for ids in by_step.values()]
    assert len(set(all_ids)) == len(all_ids)


def test_every_research_fact_cites_a_line_in_the_report(run: dict[str, Any]) -> None:
    facts = run["steps"]["research"]["output"]["facts"]
    lines = REPORT.splitlines()

    assert facts
    for fact in facts:
        assert 1 <= fact["line"] <= len(lines), fact
        assert fact["quote"].strip() and fact["quote"] in lines[fact["line"] - 1], fact


def test_run_produces_a_contract_valid_output_per_role(
    api: httpx.Client, approver: httpx.Client, run: dict[str, Any]
) -> None:
    for step_id, recorded in run["steps"].items():
        jsonschema.validate(recorded["output"], ROLES[step_id].schema)
    assert len(run["steps"]["email_writer"]["output"]) == 2

    campaign_id = run["campaign"]["id"]
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, "sent")
    assert sent["receipt"]
    assert sent["draft"]["subject"] and sent["variant_b"]["subject"]
