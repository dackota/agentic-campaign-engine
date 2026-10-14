"""Seam 1 at fast depth: a run with a budget pauses before the next model step once the budget
is reached, and the owner raising the budget resumes it to the end.

The scripted agent reports the usage set by "[agent:usage-IN-OUT]" in the report on every
reply. The cost is the default list price: $3 per million input tokens and $15 per million
output tokens, so 3 and 15 micro-dollars a token. What each step reports, the totals, the
budget amounts and the pause itself are proved lower, in tests/engine/test_cost.py,
test_budget.py, test_campaign_routes.py and test_workflow_budget_pause.py."""

import uuid

import httpx
import pytest

from tests.api.helpers import (
    FAILED,
    FINISHED,
    REPORT,
    edge,
    save_workflow,
    step,
    until_status,
    workflow_name,
)

BUDGET_PAUSED = "budget_paused"
# Two agent steps in a row; a step none of the default roles names writes the A/B emails,
# so each one makes two agent calls.
TWO_WRITERS = {
    "steps": [step("first", "agent"), step("second", "agent")],
    "edges": [edge("first", "second")],
}


def test_raising_the_budget_resumes_the_run_to_the_end(api: httpx.Client) -> None:
    name = workflow_name("cost")
    save_workflow(api, name, TWO_WRITERS)
    # The first step costs 2 * (1000 * 3 + 500 * 15) = 21000 micro-dollars, past $0.01.
    report = "\n".join(["[agent:usage-1000-500]", REPORT, f"case {uuid.uuid4().hex}"])
    created = api.post("/campaigns", json={"report": report, "workflow": name, "budget_usd": 0.01})
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    paused = until_status(api, campaign_id, BUDGET_PAUSED, FINISHED, FAILED)
    assert paused["status"] == BUDGET_PAUSED
    assert [s["step"] for s in paused["cost"]["steps"]] == ["first"]

    raised = api.post(f"/campaigns/{campaign_id}/budget", json={"budget_usd": 1})
    assert raised.status_code == 200, raised.text
    assert raised.json()["budget_usd"] == pytest.approx(1)
    finished = until_status(api, campaign_id, FINISHED, FAILED, BUDGET_PAUSED)

    assert finished["status"] == FINISHED
    assert [s["step"] for s in finished["cost"]["steps"]] == ["first", "second"]
    assert finished["cost"]["cost_usd"] == pytest.approx(0.042)
