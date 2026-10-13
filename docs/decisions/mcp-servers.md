# Decision: four read-only MCP servers we wrote, and tool reads on the run event stream

Date: 2026-10-12. Status: accepted (builder's call while building #38).

**Decision.** Each fake has a read-only MCP server in `services/mcp/ace_mcp`: Workfront,
Marketo, the CMS, and the asset library. Each is a small Streamable HTTP server (JSON-RPC:
`initialize`, `ping`, `tools/list`, `tools/call`) in the Python image, with its own
Deployment and Service in `charts/ace`, and a `RemoteMCPServer` in `agents/mcp.yaml`.

**Read-only by construction.** A tool gets a `Reader` that can only GET, and every tool is
listed with `readOnlyHint: true`. A write is an engine step after approval, not an agent
tool. `tests/tooling/test_mcp_tools.py` reads every AgentTemplate and every server's tool
list and fails when an agent binds a tool that is not marked read-only, is named like a
write, or does not exist; a planted write tool proves it.

**Why not the `mcp` SDK.** The server needs four methods. Writing them keeps the lockfile
and the image as they are. The kagent controller connects over plain HTTP, so there is no
session state to hold.

**Binding.** Only the research agent binds tools: the Workfront reads `get_project`,
`search_projects`, `get_task`, `search_tasks`. The other servers are registered and ready
for the agents that need them later.

**Tool reads in the run events.** The worker reads the tool calls off the A2A task's
artifacts (and history): parts with `metadata["kagent.dev/a2a/part-type"] = function_call`.
It records one `tool_read` event per call, with the tool's name as its reason. The scripted
agent reports a `get_project` call in the same shape at fast depth. Checked live on k3d-ace on
2026-10-12: kagent 1.0.0-alpha9 puts the `function_call` and `function_response` parts in the
reply's artifact, before the text.
