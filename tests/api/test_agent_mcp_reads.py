"""Seam 1 at fast depth: a run's events show the research step's Workfront MCP read."""

import httpx
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.helpers import AWAITING, REPORT, create_on, read_events

TOOL_READ = "tool_read"


def test_research_step_events_show_the_workfront_mcp_read(api: httpx.Client) -> None:
    events = read_events(api, create_on(api, DEFAULT_WORKFLOW_NAME, REPORT)["id"])

    assert events[-1]["status"] == AWAITING, events
    reads = [e for e in events if e["status"] == TOOL_READ]
    assert [(e["step"], e["reason"]) for e in reads] == [("research", "get_project")]
    research = {e["status"]: e["seq"] for e in events if e["step"] == "research"}
    assert research["started"] < reads[0]["seq"] < research["succeeded"]
    assert reads[0]["session"]
