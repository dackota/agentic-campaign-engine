# services/mcp

Read-only MCP servers, one per fake (decisions: `docs/decisions/mcp-servers.md`), and the
learnings search. Run one with `python -m ace_mcp.<workfront|marketo|cms|assets|learnings>`;
a fake's server reads its fake over HTTP from `ACE_*_URL`, and the learnings server reads
the database (`ACE_DATABASE_URL`). Each listens on `:8000/mcp` (Streamable HTTP) and is registered in kagent as a
`RemoteMCPServer` (`agents/mcp.yaml`).

- `workfront`: `get_project`, `search_projects`, `get_task`, `search_tasks`, `search_approvals`
- `marketo`: `list_programs`, `get_program`
- `cms`: `list_pages`, `get_page`
- `assets`: `list_assets`, `get_asset`
- `learnings`: `search_learnings`. It reads the database, not a fake: one runs per team
  (`ACE_TEAM`) and searches only that team's learnings under row-level security
  (docs/decisions/learnings-store.md)

A tool can only GET, and `tools/list` marks every tool `readOnlyHint: true`.
`tests/tooling/test_mcp_tools.py` fails when an AgentTemplate binds a tool that is not a read.

## Telemetry

An MCP server over HTTP calls `ace_engine.telemetry.instrument_app(app, "<name>")` when it
builds its app, so its spans join the campaign trace (docs/decisions/one-trace-per-campaign.md).
