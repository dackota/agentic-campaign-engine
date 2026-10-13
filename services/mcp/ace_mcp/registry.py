"""Every read-only MCP server we run, by the name of its kagent RemoteMCPServer, with its
tools. The no-write-tool check reads this."""

from collections.abc import Mapping
from types import MappingProxyType

from ace_mcp import assets, cms, learnings, marketo, workfront
from ace_mcp.server import Tool

SERVERS: Mapping[str, tuple[Tool, ...]] = MappingProxyType(
    {
        workfront.NAME: workfront.TOOLS,
        marketo.NAME: marketo.TOOLS,
        cms.NAME: cms.TOOLS,
        assets.NAME: assets.tools_for(""),
        learnings.NAME: learnings.TOOLS,
    }
)
