"""Seam 1 at fast depth: a campaign that opts in to the step cache reuses the saved result
of an agent step it has run before. The key is the step type, the agent revision digest and
a hash of the input, so a re-run of an unchanged step is a cache hit that costs nothing in
the ledger, and a new agent revision, or a changed input, misses."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.api.helpers import (
    DRAFT_ONLY,
    FAILED,
    FINISHED,
    REPORT,
    draft_cost,
    run_cached,
    save_workflow,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

SCRIPTED_INPUT_TOKENS = 1000
SCRIPTED_OUTPUT_TOKENS = 500


@pytest.fixture
def workflow(api: httpx.Client) -> str:
    name = workflow_name("cache")
    save_workflow(api, name, DRAFT_ONLY)
    return name


@pytest.fixture(autouse=True)
def default_revision(stack: Stack) -> Iterator[None]:
    stack.agent.set_revision("1")
    yield
    stack.agent.set_revision("1")


def fresh_report() -> str:
    return f"{REPORT}\ncase {uuid.uuid4().hex}"


def agent_calls(stack: Stack, campaign: dict[str, Any]) -> list[str]:
    [found] = [s for s in campaign["steps"] if s["id"] == "draft"]
    return [m for m in stack.agent.message_ids() if m.startswith(f"{found['idempotency_key']}:")]


def output_of(api: httpx.Client, campaign: dict[str, Any]) -> object:
    response = api.get(f"/campaigns/{campaign['id']}/steps")
    assert response.status_code == 200, response.text
    [found] = [s for s in response.json() if s["step"] == "draft"]
    return found["output"]


def test_first_run_is_a_miss_and_is_billed(api: httpx.Client, stack: Stack, workflow: str) -> None:
    campaign = run_cached(api, workflow, fresh_report())

    cost = draft_cost(campaign)
    assert cost["cache_hit"] is False
    # Two emails, each reply 1000 in and 500 out.
    assert (cost["input_tokens"], cost["output_tokens"]) == (2000, 1000)
    assert cost["cost_usd"] > 0
    assert len(agent_calls(stack, campaign)) == 2


def test_rerun_of_unchanged_step_is_a_cache_hit_with_zero_cost(
    api: httpx.Client, stack: Stack, workflow: str
) -> None:
    report = fresh_report()
    first = run_cached(api, workflow, report)

    second = run_cached(api, workflow, report)

    cost = draft_cost(second)
    assert cost["cache_hit"] is True
    assert (cost["input_tokens"], cost["output_tokens"], cost["cost_usd"]) == (0, 0, 0)
    assert second["cost"]["cost_usd"] == 0
    assert agent_calls(stack, second) == []
    assert output_of(api, second) == output_of(api, first)
    assert second["draft"] == first["draft"]


def test_new_agent_revision_misses_the_cache(
    api: httpx.Client, stack: Stack, workflow: str
) -> None:
    report = fresh_report()
    run_cached(api, workflow, report)

    stack.agent.set_revision("2")
    after_change = run_cached(api, workflow, report)
    stack.agent.set_revision("1")
    back_again = run_cached(api, workflow, report)

    assert draft_cost(after_change)["cache_hit"] is False
    assert draft_cost(after_change)["cost_usd"] > 0
    assert len(agent_calls(stack, after_change)) == 2
    # The first revision's entry is still there for a run on that revision.
    assert draft_cost(back_again)["cache_hit"] is True


def test_changed_input_misses_the_cache(api: httpx.Client, workflow: str) -> None:
    run_cached(api, workflow, fresh_report())

    other = run_cached(api, workflow, fresh_report())

    assert draft_cost(other)["cache_hit"] is False


def test_campaign_without_the_opt_in_never_uses_the_cache(
    api: httpx.Client, stack: Stack, workflow: str
) -> None:
    report = fresh_report()
    run_cached(api, workflow, report)

    response = api.post("/campaigns", json={"report": report, "workflow": workflow})
    assert response.status_code == 201, response.text
    plain = until_status(api, response.json()["id"], FINISHED, FAILED)

    assert draft_cost(plain)["cache_hit"] is False
    assert len(agent_calls(stack, plain)) == 2


def test_a_cache_hit_runs_even_when_the_budget_is_spent(api: httpx.Client, workflow: str) -> None:
    report = fresh_report()
    run_cached(api, workflow, report)

    second = run_cached(api, workflow, report, budget_usd=0.000001)

    assert draft_cost(second)["cache_hit"] is True
