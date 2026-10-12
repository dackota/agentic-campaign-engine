"""A read-only MCP server over HTTP (the Streamable HTTP transport, JSON replies).

It speaks the few methods an agent runtime needs: `initialize`, `ping`, `tools/list`, and
`tools/call`. Every tool is a read: a tool gets a `Reader`, which can only GET, and every
tool is listed with `readOnlyHint: true`. A tool that would write has nowhere to stand.
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import uvicorn
from ace_engine import telemetry
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
PROTOCOL_VERSION = "2025-03-26"
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
# An upstream that fails is a tool error the agent can read, not a protocol error.
MAX_TEXT_CHARS = 20_000


class Reader:
    """What a tool may do to the system it fronts: read."""

    def get(self, path: str, **params: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def get_response(self, path: str, **params: str) -> httpx.Response:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[Reader, dict[str, Any]], Any]


def schema(required: Sequence[str] = (), **properties: str) -> dict[str, Any]:
    """An object schema whose properties are all strings: name -> description."""
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in properties.items()},
        "required": list(required),
    }


def describe(tool: Tool) -> dict[str, Any]:
    """The tool as `tools/list` shows it."""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    }


def _reply(body: dict[str, Any], result: Any = None, error: tuple[int, str] | None = None) -> Any:
    envelope: dict[str, Any] = {"jsonrpc": "2.0", "id": body.get("id")}
    if error is not None:
        envelope["error"] = {"code": error[0], "message": error[1]}
    else:
        envelope["result"] = result
    return JSONResponse(envelope)


def _call(tools: dict[str, Tool], reader: Reader, params: dict[str, Any]) -> Any:
    tool = tools.get(str(params.get("name")))
    if tool is None:
        return None
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return {
            "content": [{"type": "text", "text": "arguments must be an object"}],
            "isError": True,
        }
    try:
        text = json.dumps(tool.run(reader, arguments), default=str)
        is_error = False
    except Exception as exc:  # the agent reads the failure; the server stays up
        log.warning("tool %s failed: %r", tool.name, exc)
        text, is_error = f"tool {tool.name} failed: {exc}", True
    return {"content": [{"type": "text", "text": text[:MAX_TEXT_CHARS]}], "isError": is_error}


def create_app(name: str, tools: Sequence[Tool], reader: Reader) -> FastAPI:
    by_name = {t.name: t for t in tools}
    app = FastAPI()
    telemetry.instrument_app(app, name)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(MCP_PATH, response_model=None)
    async def rpc(request: Request) -> Any:
        try:
            body = await request.json()
        except ValueError:
            return _reply({}, error=(INVALID_REQUEST, "body is not JSON"))
        if not isinstance(body, dict) or "method" not in body:
            return _reply({}, error=(INVALID_REQUEST, "not a JSON-RPC request"))
        method, params = body["method"], body.get("params") or {}
        if "id" not in body:
            return Response(status_code=202)  # a notification
        if not isinstance(params, dict):
            return _reply(body, error=(INVALID_PARAMS, "params must be an object"))
        if method == "initialize":
            return _reply(
                body,
                {
                    "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": name, "version": "0.1.0"},
                },
            )
        if method == "ping":
            return _reply(body, {})
        if method == "tools/list":
            return _reply(body, {"tools": [describe(t) for t in tools]})
        if method == "tools/call":
            result = _call(by_name, reader, params)
            if result is None:
                return _reply(body, error=(INVALID_PARAMS, f"unknown tool {params.get('name')}"))
            return _reply(body, result)
        return _reply(body, error=(METHOD_NOT_FOUND, f"method not found: {method}"))

    return app


HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def serve(app: FastAPI) -> None:
    """Run the app until the process stops."""
    uvicorn.run(app, host=HOST, port=PORT)
