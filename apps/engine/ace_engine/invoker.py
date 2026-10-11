"""Agent invoker: ask an agent over A2A and return output that fits a schema.

Speaks the JSON-RPC `SendMessage` contract the kagent 1.x controller serves under
/agents/<namespace>/<agent> (version 1.0; checked live on k3d-ace, see docs/sources.md).
Hides the call, session reuse, an idempotency key per message, a timeout, and one repair
attempt when the reply breaks the schema. A session (contextId) is issued by the agent: the
first message names none, and the repair reuses the one the agent returned.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from ace_engine.contracts import violations

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class AgentOutputInvalid(Exception):
    """The agent replied twice without output that fits the contract."""


class AgentCallFailed(Exception):
    """The agent could not be reached or answered with an error."""


@dataclass(frozen=True)
class Invocation:
    output: dict[str, Any]
    session_id: str
    usage: dict[str, Any] | None


A2A_VERSION = "1.0"
USAGE_KEY = "kagent.dev/a2a/usage"


def _reply_text(task: dict[str, Any]) -> str:
    parts: list[dict[str, Any]] = []
    for artifact in task.get("artifacts") or []:
        parts.extend(artifact.get("parts", []))
    if not parts:
        parts = (task.get("status", {}).get("message") or {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _usage(task: dict[str, Any]) -> dict[str, Any] | None:
    for artifact in task.get("artifacts") or []:
        usage = (artifact.get("metadata") or {}).get(USAGE_KEY)
        if usage is not None:
            found: dict[str, Any] = usage
            return found
    return None


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
    session_id: str | None,
    message_id: str,
    text: str,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": message_id,
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if session_id is not None:
        message["contextId"] = session_id
    payload = {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "SendMessage",
        "params": {"message": message},
    }
    try:
        response = await client.post(agent_url, json=payload, headers={"A2A-Version": A2A_VERSION})
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AgentCallFailed(f"agent call failed: {exc!r}") from exc
    if "error" in body:
        raise AgentCallFailed(f"agent returned an error: {body['error']}")
    try:
        task: dict[str, Any] = body["result"]["task"]
    except (KeyError, TypeError) as exc:
        raise AgentCallFailed(f"agent reply has no task: {body!r}") from exc
    return task


async def invoke(
    client: httpx.AsyncClient,
    agent_url: str,
    session_key: str,
    prompt: str,
    schema: dict[str, Any],
) -> Invocation:
    result = await _send(client, agent_url, None, f"{session_key}:1", prompt)
    session_id: str = result["contextId"]
    output, problems = _parse(_reply_text(result), schema)
    if output is None:
        repair = (
            "Your reply did not fit the contract: "
            + "; ".join(problems)
            + ". Reply again with only the corrected JSON."
        )
        result = await _send(client, agent_url, session_id, f"{session_key}:2", repair)
        output, problems = _parse(_reply_text(result), schema)
    if output is None:
        raise AgentOutputInvalid(
            "reply broke the contract after one repair: " + "; ".join(problems)
        )
    return Invocation(
        output=output,
        session_id=result.get("contextId", session_id),
        usage=_usage(result),
    )


def new_session_key() -> str:
    return str(uuid.uuid4())
