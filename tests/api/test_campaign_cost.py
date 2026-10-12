"""Seam 1 at fast depth: every agent step reports the tokens and cost its replies used,
the campaign's totals add up over its steps, and a run with a budget pauses before the
next model step once the budget is reached, until the owner raises it.

The scripted agent reports the usage set by "[agent:usage-IN-OUT]" in the report on every
reply. The cost is the default list price: $3 per million input tokens and $15 per million
output tokens, so 3 and 15 micro-dollars a token."""

import uuid
from typing import Any

import httpx
import pytest

from tests.api.helpers import (
    AWAITING,
    FAILED,
    FINISHED,
    REPORT,
    create_on,
    edge,
    read_events,
    save_workflow,
    settle,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

BUDGET_PAUSED = "budget_paused"
SCRIPTED_MODEL = "scripted-model"
# Two agent steps in a row; a step none of the default roles names writes the A/B emails,
# so each one makes two agent calls.
TWO_WRITERS = {
    "steps": [step("first", "agent"), step("second", "agent")],
    "edges": [edge("first", "second")],
}


def report(usage: str) -> str:
    """A report no other test shares, carrying the scripted usage for each reply."""
    return "\n".join([f"[agent:usage-{usage}]", REPORT, f"case {uuid.uuid4().hex}"])


def start(api: httpx.Client, dag: dict[str, Any], text: str, **extra: object) -> dict[str, Any]:
    name = workflow_name("cost")
    save_workflow(api, name, dag)
    if not extra:
        return create_on(api, name, text)
    response = api.post("/campaigns", json={"report": text, "workflow": name, **extra})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def calls_for(stack: Stack, campaign: dict[str, Any], step_id: str) -> list[str]:
    [found] = [s for s in campaign["steps"] if s["id"] == step_id]
    return [m for m in stack.agent.message_ids() if m.startswith(f"{found['idempotency_key']}:")]


def test_each_step_reports_the_scripted_tokens_and_cost(api: httpx.Client) -> None:
    created = api.post("/campaigns", json={"report": report("1200-300")})
    assert created.status_code == 201, created.text

    campaign = settle(api, created.json()["id"])

    assert campaign["status"] == AWAITING
    # The email draft step asks for two emails: two replies of 1200 in and 300 out, each
    # costing 1200 * 3 + 300 * 15 = 8100 micro-dollars.
    assert campaign["cost"]["steps"] == [
        {
            "step": "email_draft",
            "model": SCRIPTED_MODEL,
            "input_tokens": 2400,
            "output_tokens": 600,
            "total_tokens": 3000,
            "cost_usd": pytest.approx(0.0162),
            "cache_hit": False,
        }
    ]


def test_usage_with_only_a_total_is_booked_at_the_output_price(api: httpx.Client) -> None:
    created = api.post("/campaigns", json={"report": report("total-700")})
    assert created.status_code == 201, created.text

    campaign = settle(api, created.json()["id"])

    # Two replies of 700 tokens with no split: booked as output, the dearer side, so a
    # budget never undercounts. 1400 * 15 = 21000 micro-dollars.
    [email_draft] = campaign["cost"]["steps"]
    assert (email_draft["input_tokens"], email_draft["output_tokens"]) == (0, 1400)
    assert email_draft["total_tokens"] == 1400
    assert email_draft["cost_usd"] == pytest.approx(0.021)


def test_campaign_totals_add_up_over_its_steps(api: httpx.Client) -> None:
    dag = {
        "steps": [step("strategist", "agent"), step("research", "agent"), step("writer", "agent")],
        "edges": [edge("strategist", "research"), edge("research", "writer")],
    }

    created = start(api, dag, report("1000-250"))
    campaign = until_status(api, created["id"], FINISHED, FAILED)

    assert campaign["status"] == FINISHED
    cost = campaign["cost"]
    assert [s["step"] for s in cost["steps"]] == ["strategist", "research", "writer"]
    # Four replies (the writer makes two) of 1000 in and 250 out, 6750 micro-dollars each.
    assert (cost["input_tokens"], cost["output_tokens"], cost["total_tokens"]) == (
        4000,
        1000,
        5000,
    )
    assert cost["cost_usd"] == pytest.approx(0.027)
    assert sum(s["input_tokens"] for s in cost["steps"]) == cost["input_tokens"]
    assert sum(s["output_tokens"] for s in cost["steps"]) == cost["output_tokens"]
    assert sum(s["total_tokens"] for s in cost["steps"]) == cost["total_tokens"]
    assert sum(s["cost_usd"] for s in cost["steps"]) == pytest.approx(cost["cost_usd"])


def test_run_pauses_before_the_next_model_step_at_its_budget(
    stack: Stack, api: httpx.Client
) -> None:
    # The first step costs 2 * (1000 * 3 + 500 * 15) = 21000 micro-dollars, past $0.01.
    created = start(api, TWO_WRITERS, report("1000-500"), budget_usd=0.01)
    assert created["budget_usd"] == pytest.approx(0.01)

    paused = until_status(api, created["id"], BUDGET_PAUSED, FINISHED, FAILED)
    events = read_events(api, created["id"])

    assert paused["status"] == BUDGET_PAUSED
    assert paused["cost"]["cost_usd"] == pytest.approx(0.021)
    assert [s["step"] for s in paused["cost"]["steps"]] == ["first"]
    assert calls_for(stack, created, "second") == []
    assert ("second", "started") not in [(e["step"], e["status"]) for e in events]
    assert (events[-1]["step"], events[-1]["status"]) == ("run", BUDGET_PAUSED)


def test_raising_the_budget_resumes_the_run_to_the_end(api: httpx.Client) -> None:
    created = start(api, TWO_WRITERS, report("1000-500"), budget_usd=0.01)
    until_status(api, created["id"], BUDGET_PAUSED, FINISHED, FAILED)

    raised = api.post(f"/campaigns/{created['id']}/budget", json={"budget_usd": 1})
    assert raised.status_code == 200, raised.text
    assert raised.json()["budget_usd"] == pytest.approx(1)
    finished = until_status(api, created["id"], FINISHED, FAILED, BUDGET_PAUSED)

    assert finished["status"] == FINISHED
    assert [s["step"] for s in finished["cost"]["steps"]] == ["first", "second"]
    assert finished["cost"]["cost_usd"] == pytest.approx(0.042)


def test_a_budget_raise_must_clear_what_was_spent(api: httpx.Client) -> None:
    created = start(api, TWO_WRITERS, report("1000-500"), budget_usd=0.01)
    until_status(api, created["id"], BUDGET_PAUSED, FINISHED, FAILED)

    # $0.021 is spent, so $0.02 would pause again at once.
    response = api.post(f"/campaigns/{created['id']}/budget", json={"budget_usd": 0.02})

    assert response.status_code == 422, response.text
    assert "spent" in response.text
    assert api.get(f"/campaigns/{created['id']}").json()["status"] == BUDGET_PAUSED


def test_only_an_owner_raises_the_budget(api: httpx.Client, approver: httpx.Client) -> None:
    created = start(api, TWO_WRITERS, report("1000-500"), budget_usd=0.01)
    until_status(api, created["id"], BUDGET_PAUSED, FINISHED, FAILED)

    response = approver.post(f"/campaigns/{created['id']}/budget", json={"budget_usd": 1})

    assert response.status_code == 403, response.text
    assert api.get(f"/campaigns/{created['id']}").json()["status"] == BUDGET_PAUSED


@pytest.mark.parametrize("budget", [0, -1, "lots"])
def test_campaign_budget_must_be_a_positive_amount(api: httpx.Client, budget: float | str) -> None:
    response = api.post("/campaigns", json={"report": REPORT, "budget_usd": budget})

    assert response.status_code == 422, response.text
