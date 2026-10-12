"""The no-write-tool check: every tool an AgentTemplate binds must be a read.

A template binds `spec.tools[].mcp` = a RemoteMCPServer and the tool names to use (none
named means every tool of that server). A bound tool is a write when its server marks it
anything but `readOnlyHint: true`, when its name starts with a write verb, or when the
server has no such tool.
"""

from typing import Any

WRITE_VERBS = (
    "create",
    "update",
    "delete",
    "remove",
    "put",
    "post",
    "patch",
    "send",
    "publish",
    "set",
    "upsert",
    "write",
    "approve",
)

ServerTools = dict[str, list[dict[str, Any]]]


def write_tool_bindings(templates: list[dict[str, Any]], servers: ServerTools) -> list[str]:
    """One problem per tool binding that is, or may be, a write; empty when all are reads."""
    problems: list[str] = []
    for template in templates:
        owner = template["metadata"]["name"]
        for binding in template.get("spec", {}).get("tools") or []:
            mcp = binding.get("mcp")
            if mcp is None:
                continue
            server = mcp["server"]["name"]
            known = {t["name"]: t for t in servers.get(server, [])}
            if server not in servers:
                problems.append(
                    f"{owner}: binds {server}, which is not one of our read-only servers"
                )
                continue
            for name in mcp.get("tools") or list(known):
                tool = known.get(name)
                if tool is None:
                    problems.append(f"{owner}: binds {server}/{name}, which the server lacks")
                elif tool.get("annotations", {}).get("readOnlyHint") is not True:
                    problems.append(f"{owner}: {server}/{name} is not marked read-only")
                elif name.startswith(WRITE_VERBS):
                    problems.append(f"{owner}: {server}/{name} is named like a write")
    return problems
