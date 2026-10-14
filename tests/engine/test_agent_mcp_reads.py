"""A run's events show the research step's Workfront MCP read: the tools an agent called while
it answered are recorded as events of the step, in its writer session, before it succeeds."""

from typing import Any

from ace_engine import db, invoker
from sqlalchemy.engine import Engine

from tests.support.dag import REPORT
from tests.support.scripted_worker import run_step, scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

FUNCTION_CALL = {invoker.PART_TYPE_KEY: invoker.FUNCTION_CALL}


def test_research_step_events_show_the_workfront_mcp_read(sqlite_engine: Engine) -> None:
    campaign = seed_campaign(sqlite_engine, CampaignSeed(status=db.DRAFTING))

    result = run_step(scripted_worker(sqlite_engine), campaign, "research", REPORT)

    events = db.events_after(sqlite_engine, campaign, 0)
    reads = [e for e in events if e.status == db.TOOL_READ]
    assert [(e.step, e.reason) for e in reads] == [("research", "get_project")]
    by_status = {e.status: e.seq for e in events if e.step == "research"}
    assert by_status[db.STEP_STARTED] < reads[0].seq < by_status[db.STEP_SUCCEEDED]
    assert reads[0].session == result["session"]


def test_a_step_whose_agent_called_no_tool_records_no_read(sqlite_engine: Engine) -> None:
    campaign = seed_campaign(sqlite_engine, CampaignSeed(status=db.DRAFTING))

    run_step(scripted_worker(sqlite_engine), campaign, "strategist", REPORT)

    assert [
        e for e in db.events_after(sqlite_engine, campaign, 0) if e.status == db.TOOL_READ
    ] == []


def test_the_tools_an_agent_called_are_read_off_its_reply_in_call_order() -> None:
    def part(kind: str, name: str) -> dict[str, Any]:
        return {"data": {"name": name}, "metadata": {invoker.PART_TYPE_KEY: kind}}

    task = {
        "artifacts": [
            {"parts": [part("function_call", "search_projects"), part("function_response", "x")]}
        ],
        "history": [{"parts": [part("function_call", "get_project"), {"text": "hello"}]}],
    }

    assert invoker._tool_calls_of(task) == ("search_projects", "get_project")
    assert invoker._tool_calls_of({}) == ()
    assert invoker._tool_calls_of({"artifacts": [{"parts": [{"data": {"name": 3}}]}]}) == ()
