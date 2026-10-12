"""Every read-only MCP server we run, by the name of its kagent RemoteMCPServer, with its
tools. The no-write-tool check reads this."""

from ace_mcp import assets, cms, marketo, workfront
from ace_mcp.server import Tool

SERVERS: dict[str, tuple[Tool, ...]] = {
    workfront.NAME: workfront.TOOLS,
    marketo.NAME: marketo.TOOLS,
    cms.NAME: cms.TOOLS,
    assets.NAME: assets.tools_for(""),
}
