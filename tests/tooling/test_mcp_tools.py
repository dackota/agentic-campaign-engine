"""Agents read the stack through read-only MCP servers, and no agent binds a write tool."""

import asyncio
import copy
from typing import Any

import httpx
from ace_engine import invoker
from ace_engine.agent_roles import ROLES
from ace_mcp.registry import SERVERS
from ace_mcp.server import describe

from tests.tooling.chart_files import by_kind, render
from tests.tooling.gateway_files import ROOT, yaml_docs
from tests.tooling.mcp_files import write_tool_bindings

MCP_MANIFEST = ROOT / "agents/mcp.yaml"
TEMPLATES = ROOT / "agents/templates.yaml"
RESEARCH = "ace-research"
WORKFRONT = "ace-mcp-workfront"
WORKFRONT_READS = ["get_project", "search_projects", "get_task", "search_tasks"]
LEARNINGS = "ace-mcp-learnings"
LEARNINGS_SEARCH = "search_learnings"
# The agents that read past learnings before they write.
LEARNING_READERS = ("research", "email_writer", "landing_page", "social", "one_pager")
TEAMS = ("demand-gen", "product-marketing")


def server_tools() -> dict[str, list[dict[str, Any]]]:
    return {name: [describe(t) for t in tools] for name, tools in SERVERS.items()}


def templates() -> list[dict[str, Any]]:
    return [d for d in yaml_docs(TEMPLATES) if d["kind"] == "AgentTemplate"]


def binding(server: str, tools: list[str]) -> dict[str, Any]:
    return {
        "mcp": {
            "server": {"kind": "RemoteMCPServer", "name": server},
            "tools": tools,
        }
    }


def test_each_fake_has_a_remote_mcp_server_in_kagent() -> None:
    remote = {
        d["metadata"]["name"]: d for d in yaml_docs(MCP_MANIFEST) if d["kind"] == "RemoteMCPServer"
    }
    docs = render()
    deployments = {d["metadata"]["name"] for d in by_kind(docs, "Deployment")}
    services = {d["metadata"]["name"] for d in by_kind(docs, "Service")}

    assert set(remote) == set(SERVERS) and len(SERVERS) == 5
    for name, server in remote.items():
        assert server["apiVersion"] == "api.kagent.dev/v1alpha3"
        assert server["metadata"]["namespace"] == "kagent"
        assert server["spec"]["protocol"] == "STREAMABLE_HTTP"
        assert server["spec"]["url"] == f"http://{name}.ace.svc.cluster.local:8000/mcp"
        assert name in deployments and name in services
    # The learnings search reads one team's rows: each team has its own server.
    assert {f"{LEARNINGS}-{team}" for team in TEAMS} <= deployments & services
    install = (ROOT / "platform/install.sh").read_text()
    assert install.index("agents/mcp.yaml") < install.index("agents/templates.yaml")


def test_no_agent_template_binds_a_write_tool() -> None:
    assert write_tool_bindings(templates(), server_tools()) == []


def test_check_fails_on_a_planted_write_tool() -> None:
    planted = server_tools()
    planted[WORKFRONT].append(
        {"name": "create_task", "annotations": {"readOnlyHint": False}, "inputSchema": {}}
    )
    bad = copy.deepcopy(templates())
    research = next(t for t in bad if t["metadata"]["name"] == RESEARCH)
    research["spec"]["tools"].append(binding(WORKFRONT, ["create_task"]))
    disguised = {**planted}
    disguised[WORKFRONT] = [
        *planted[WORKFRONT][:-1],
        {"name": "update_task", "annotations": {"readOnlyHint": True}, "inputSchema": {}},
    ]
    research["spec"]["tools"].append(binding(WORKFRONT, ["update_task"]))

    assert any("create_task" in p for p in write_tool_bindings(bad, planted))
    assert any("update_task" in p for p in write_tool_bindings(bad, disguised))
    assert write_tool_bindings(
        [{"metadata": {"name": "x"}, "spec": {"tools": [binding("someone-elses", ["anything"])]}}],
        server_tools(),
    )


def test_research_and_writers_bind_the_learnings_search_and_say_to_use_it_first() -> None:
    by_name = {t["metadata"]["name"]: t for t in templates()}
    learnings = binding(LEARNINGS, [LEARNINGS_SEARCH])

    assert by_name[RESEARCH]["spec"]["tools"] == [binding(WORKFRONT, WORKFRONT_READS), learnings]
    for step_id, role in ROLES.items():
        tools = by_name[role.template]["spec"].get("tools")
        if step_id == "research":
            continue
        if step_id in LEARNING_READERS:
            assert tools == [learnings], role.template
        else:
            assert not tools, role.template
    for step_id in LEARNING_READERS:
        assert f"Before you write, call the {LEARNINGS_SEARCH} tool" in ROLES[step_id].prompt
    assert "get_project" in ROLES["research"].prompt


def test_invoker_reads_the_tools_an_agent_called_off_the_task() -> None:
    call = {
        "data": {"name": "get_project", "args": {"project_id": "p1"}, "id": "c1"},
        "metadata": {"kagent.dev/a2a/part-type": "function_call"},
    }
    response = {
        "data": {"name": "get_project", "response": {}, "id": "c1"},
        "metadata": {"kagent.dev/a2a/part-type": "function_response"},
    }
    task = {
        "id": "t",
        "contextId": "ctx",
        # Alpha9 puts the tool parts in the artifact before the text (seen live on k3d-ace).
        "artifacts": [{"parts": [call, response, {"text": '{"ok": true}'}]}],
    }

    def reply(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "result": {"task": task}})

    async def run() -> invoker.Invocation:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            return await invoker.invoke(
                client,
                "http://agent",
                invoker.AgentCall("k", "p", {"type": "object"}),
            )

    assert asyncio.run(run()).tool_calls == ("get_project",)


def api_group_problems(docs: list[dict[str, Any]]) -> list[str]:
    """The live kagent CRD rejects apiGroup on spec.tools[].mcp.server."""
    return [
        d["metadata"]["name"]
        for d in docs
        for tool in d["spec"].get("tools") or []
        if "apiGroup" in tool.get("mcp", {}).get("server", {})
    ]


def test_no_agent_template_sets_api_group_on_an_mcp_server() -> None:
    assert api_group_problems(templates()) == []


def test_api_group_check_fails_on_a_planted_api_group() -> None:
    bad = copy.deepcopy(templates())
    research = next(t for t in bad if t["metadata"]["name"] == RESEARCH)
    research["spec"]["tools"][0]["mcp"]["server"]["apiGroup"] = "api.kagent.dev"

    assert api_group_problems(bad) == [RESEARCH]


def test_sources_row_for_template_tools_has_no_api_group_and_is_checked_live() -> None:
    rows = [
        line
        for line in (ROOT / "docs/sources.md").read_text().splitlines()
        if "agenttemplate" in line and "spec.tools" in line
    ]

    assert len(rows) == 1
    assert "{apiGroup" not in rows[0] and "apiGroup," not in rows[0]
    assert "Unchecked live" not in rows[0] and "2026-10-12" in rows[0]
