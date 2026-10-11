"""Agent invoker: ask an agent over A2A (JSON-RPC `message/send`, the fast-depth wire;
kagent 1.x serves gRPC, so live depth swaps the transport, see docs/sources.md)
and return output that fits a schema.

Hides the A2A `message/send` call, session reuse (the A2A contextId), an idempotency
key per message, a timeout, and one repair attempt when the reply breaks the schema.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from ace_engine.contracts import violations
from ace_engine.cost import Usage, usage_from

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class AgentOutputInvalid(Exception):
    """The agent replied twice without output that fits the contract."""


class AgentCallFailed(Exception):
    """The agent could not be reached or answered with an error."""


@dataclass(frozen=True)
class Invocation:
    output: dict[str, Any]
    session_id: str
    # The tokens every call of this invocation used, the repair attempt's included.
    usage: Usage


def _reply_text(result: dict[str, Any]) -> str:
    parts: list[dict[str, Any]] = []
    for artifact in result.get("artifacts") or []:
        parts.extend(artifact.get("parts", []))
    if not parts:
        parts = (result.get("status", {}).get("message") or {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if p.get("kind") == "text")


def _parse(text: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    candidate = fenced.group(1) if fenced else stripped
    try:
        loaded = json.loads(candidate)
    except json.JSONDecodeError:
        return None, ["reply is not valid JSON"]
    problems = violations(loaded, schema)
    if problems:
        return None, problems
    return loaded, []


async def _send(
    client: httpx.AsyncClient,
    agent_url: str,
    session_id: str,
    message_id: str,
    text: str,
) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": message_id,
                "contextId": session_id,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    try:
        response = await client.post(agent_url, json=payload)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AgentCallFailed(f"agent call failed: {exc!r}") from exc
    if "error" in body:
        raise AgentCallFailed(f"agent returned an error: {body['error']}")
    result: dict[str, Any] = body["result"]
    return result


async def invoke(
    client: httpx.AsyncClient,
    agent_url: str,
    session_key: str,
    prompt: str,
    schema: dict[str, Any],
) -> Invocation:
    session_id = session_key
    result = await _send(client, agent_url, session_id, f"{session_key}:1", prompt)
    usage = _usage_of(result)
    output, problems = _parse(_reply_text(result), schema)
    if output is None:
        repair = (
            "Your reply did not fit the contract: "
            + "; ".join(problems)
            + ". Reply again with only the corrected JSON."
        )
        result = await _send(client, agent_url, session_id, f"{session_key}:2", repair)
        usage = usage + _usage_of(result)
        output, problems = _parse(_reply_text(result), schema)
    if output is None:
        raise AgentOutputInvalid(
            "reply broke the contract after one repair: " + "; ".join(problems)
        )
    return Invocation(
        output=output,
        session_id=result.get("contextId", session_id),
        usage=usage,
    )


def _usage_of(result: dict[str, Any]) -> Usage:
    """The token usage on an A2A task reply: `metadata.usage`, as the ADR in
    docs/decisions/token-usage-per-campaign.md decides."""
    metadata = result.get("metadata")
    return usage_from(metadata.get("usage") if isinstance(metadata, dict) else None)


def new_session_key() -> str:
    return str(uuid.uuid4())
