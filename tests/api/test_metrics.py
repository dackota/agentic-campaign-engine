"""Seam 1 at fast depth: the metrics the alert rules read. A run that fails counts a failed
run, the cost of each step adds to the cost counter, and each brand review records an eval
score (1 for a pass, 0 for a fix)."""

import json

import httpx

from tests.api.helpers import (
    FAILED,
    FINISHED,
    REPORT,
    create_on,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

FAST_RETRY = {"maximum_attempts": 1, "initial_interval_seconds": 0.1}
PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
PASS = {"verdict": "pass", "issues": []}
FIX = {"verdict": "fix", "issues": [{"check": "banned_claim", "detail": "banned claim"}]}


def run_one(api: httpx.Client, name: str, report: str) -> str:
    return str(create_on(api, name, report)["id"])


def test_a_failed_run_counts_as_failed(stack: Stack, api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(api, name, {"steps": [step("writer", "agent", retry=FAST_RETRY)], "edges": []})
    before = stack.metric_total("ace.runs", outcome="failed")

    campaign_id = run_one(api, name, f"[agent:down-5]\n{REPORT}\n{name}")
    assert until_status(api, campaign_id, FAILED, FINISHED)["status"] == FAILED

    assert stack.metric_total("ace.runs", outcome="failed") == before + 1


def test_a_finished_run_counts_as_finished(stack: Stack, api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(api, name, {"steps": [step("pause", "wait", duration_seconds=1)], "edges": []})
    before = stack.metric_total("ace.runs", outcome="finished")

    campaign_id = run_one(api, name, f"{REPORT}\n{name}")
    until_status(api, campaign_id, FINISHED)

    assert stack.metric_total("ace.runs", outcome="finished") == before + 1


def test_step_cost_adds_to_the_cost_counter(stack: Stack, api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(api, name, {"steps": [step("first", "agent")], "edges": []})
    before = stack.metric_total("ace.cost.dollars")

    campaign_id = run_one(api, name, f"[agent:usage-1200-300]\n{REPORT}\n{name}")
    until_status(api, campaign_id, FINISHED)

    # Two replies (the A/B emails) at $0.0081 each.
    assert abs(stack.metric_total("ace.cost.dollars") - before - 0.0162) < 1e-9


def test_each_brand_review_records_an_eval_score(stack: Stack, api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(
        api,
        name,
        {"steps": [step("landing_page", "agent", review_rounds=2)], "edges": []},
    )
    stack.agent.script([json.dumps(r) for r in (PAGE, FIX, PAGE, PASS)])
    count_before = stack.metric_count("ace.eval.score")
    sum_before = stack.metric_total("ace.eval.score")

    until_status(api, run_one(api, name, f"{REPORT}\n{name}"), FINISHED)

    assert stack.metric_count("ace.eval.score") == count_before + 2
    assert stack.metric_total("ace.eval.score") == sum_before + 1.0
