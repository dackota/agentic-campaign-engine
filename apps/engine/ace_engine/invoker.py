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
    # The names of the tools the agent called while it answered (MCP reads), in call order.
    tool_calls: tuple[str, ...] = ()


A2A_VERSION = "1.0"
USAGE_KEY = "kagent.dev/a2a/usage"
TASK_FAILED = "TASK_STATE_FAILED"
# kagent marks the A2A parts that record a tool call: `metadata["kagent.dev/a2a/part-type"]` is
# "function_call" and `data.name` is the tool. Alpha9 puts them in the reply's artifacts (seen
# live on k3d-ace, 2026-10-12); the task's history is read too.
PART_TYPE_KEY = "kagent.dev/a2a/part-type"
FUNCTION_CALL = "function_call"


def _reply_text(task: dict[str, Any]) -> str:
    parts: list[dict[str, Any]] = []
    for artifact in task.get("artifacts") or []:
        parts.extend(artifact.get("parts", []))
    if not parts:
        parts = (task.get("status", {}).get("message") or {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


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
    # kagent answers a failed model call (a 429 or 403 at the gateway) with a failed task whose
    # status message holds the error. That is a failed call to retry, not a reply to repair.
    if (task.get("status") or {}).get("state") == TASK_FAILED:
        raise AgentCallFailed(f"agent task failed: {_reply_text(task)}")
    return task


@dataclass(frozen=True)
class AgentCall:
    """One question to an agent. `session_id` is the session the agent issued for an earlier
    question (a fix the reviewer asked for goes to the same session); none opens a new one.
    A later `turn` gets message ids of its own."""

    session_key: str
    prompt: str
    schema: dict[str, Any]
    turn: int = 0
    session_id: str | None = None


async def invoke(client: httpx.AsyncClient, agent_url: str, call: AgentCall) -> Invocation:
    """Ask in a session: the agent issues it on the first question, the repair reuses it."""
    prompt, schema = call.prompt, call.schema
    prefix = call.session_key if call.turn == 0 else f"{call.session_key}:r{call.turn}"
    result = await _send(client, agent_url, call.session_id, f"{prefix}:1", prompt)
    session_id = result.get("contextId")
    if not isinstance(session_id, str):
        raise AgentCallFailed("agent reply carries no contextId")
    usage = _usage_of(result)
    tool_calls = _tool_calls_of(result)
    output, problems = _parse(_reply_text(result), schema)
    if output is None:
        repair = (
            "Your reply did not fit the contract: "
            + "; ".join(problems)
            + ". Reply again with only the corrected JSON."
        )
        result = await _send(client, agent_url, session_id, f"{prefix}:2", repair)
        usage = usage + _usage_of(result)
        tool_calls = tool_calls + _tool_calls_of(result)
        output, problems = _parse(_reply_text(result), schema)
    if output is None:
        raise AgentOutputInvalid(
            "reply broke the contract after one repair: " + "; ".join(problems)
        )
    return Invocation(
        output=output,
        session_id=result.get("contextId", session_id),
        usage=usage,
        tool_calls=tool_calls,
    )


def _tool_calls_of(task: dict[str, Any]) -> tuple[str, ...]:
    """The tools the agent called to answer, read off the task's artifacts and history."""
    names: list[str] = []
    for message in [*(task.get("artifacts") or []), *(task.get("history") or [])]:
        for part in message.get("parts") or []:
            data = part.get("data")
            kind = (part.get("metadata") or {}).get(PART_TYPE_KEY)
            if (
                kind == FUNCTION_CALL
                and isinstance(data, dict)
                and isinstance(data.get("name"), str)
            ):
                names.append(data["name"])
    return tuple(names)


def _usage_of(task: dict[str, Any]) -> Usage:
    """The token usage on an A2A task reply. kagent reports it on the artifact metadata under
    `kagent.dev/a2a/usage`; the ADR in docs/decisions/token-usage-per-campaign.md names
    `metadata.usage` on the task, which is read when no artifact carries it."""
    for artifact in task.get("artifacts") or []:
        reported = (artifact.get("metadata") or {}).get(USAGE_KEY)
        if reported is not None:
            return usage_from(reported)
    metadata = task.get("metadata")
    return usage_from(metadata.get("usage") if isinstance(metadata, dict) else None)


def new_session_key() -> str:
    return str(uuid.uuid4())
