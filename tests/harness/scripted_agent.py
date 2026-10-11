"""A scripted agent for fast depth: an A2A JSON-RPC (`message/send`) stand-in.

kagent 1.x itself serves gRPC A2A (see docs/sources.md); live depth will need a gRPC
client. Fast depth only needs the message shape, so this speaks JSON-RPC over HTTP.

By default it plays the role whose prompt opens the message (strategist, research, a
writer), or the email writer when none matches: it reads the threat report out of the
message and replies with output that fits that role's contract. A test can queue
exact replies with `script()` to play a misbehaving agent.
"""

import asyncio
import json
import re
import threading
import uuid
from typing import Any

from ace_engine.agent_roles import ROLES
from ace_engine.contracts import REPORT_MARKER
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

JSONRPC_METHOD_NOT_FOUND = -32601
SUBJECT_HEADLINE_CHARS = 80
BODY_REPORT_CHARS = 300
SOCIAL_POST_CHARS = 280
# Markers in a threat report steer the default writer, so a browser test can pick a
# behaviour without access to the agent: hold the reply, or reply with broken JSON.
SLOW_MARKER = "[agent:slow]"
BAD_JSON_MARKER = "[agent:bad-json]"
SLOW_REPLY_SECONDS = 1.5
# "[agent:down-N]" in a report makes the first N calls that carry that report answer with
# an A2A error, so a step fails on cue and a later attempt succeeds.
DOWN_MARKER = re.compile(r"\[agent:down-(\d{1,2})\]")
JSONRPC_AGENT_DOWN = -32000
# The worker asks for the A/B test's second email with this phrase in its prompt.
VARIANT_B_PHRASE = "variant B"
# A step that works from earlier steps' output (a writer) takes this long to answer, so
# writers that start together are still running together.
WRITER_REPLY_SECONDS = 0.5
CONTEXT_MARKER = "OUTPUT OF "
MAX_SCRIPTED_FACTS = 3
# What every scripted reply reports it used, as kagent reports usage in task metadata.
SCRIPTED_USAGE = {"input_tokens": 120, "output_tokens": 45}


class ScriptedAgent:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._replies: list[str] = []
        self._modes: dict[str, str] = {}
        self._failed: dict[str, int] = {}
        self._message_ids: list[str] = []
        self.app = self._build_app()

    def script(self, replies: list[str]) -> None:
        """Queue exact reply texts; they are used before the default writer."""
        with self._lock:
            self._replies = list(replies)

    def message_ids(self) -> list[str]:
        """The A2A messageId of every call so far, in arrival order."""
        with self._lock:
            return list(self._message_ids)

    def _is_down(self, text: str, message_id: str) -> bool:
        """Record the call; True when it must fail because its report says the agent is down."""
        report = text.split(REPORT_MARKER, 1)[-1]
        with self._lock:
            self._message_ids.append(message_id)
            found = DOWN_MARKER.search(report)
            if found is None or self._failed.get(report, 0) >= int(found.group(1)):
                return False
            self._failed[report] = self._failed.get(report, 0) + 1
            return True

    def _next_reply(self, text: str, context_id: str) -> tuple[str, bool]:
        """The reply text and whether to hold it back a moment."""
        with self._lock:
            if self._replies:
                return self._replies.pop(0), False
            for marker in (SLOW_MARKER, BAD_JSON_MARKER):
                if marker in text:
                    self._modes[context_id] = marker
            mode = self._modes.get(context_id)
        if mode == BAD_JSON_MARKER:
            return "this is not json", False
        is_writer = CONTEXT_MARKER in text
        return json.dumps(default_reply(text)), mode == SLOW_MARKER or is_writer

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/readyz")
        def readyz() -> dict[str, str]:
            return {"status": "ok"}

        @app.post("/")
        async def rpc(request: Request) -> JSONResponse:
            body = await request.json()
            if body.get("method") != "message/send":
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": JSONRPC_METHOD_NOT_FOUND, "message": "method not found"},
                    }
                )
            message = body["params"]["message"]
            text = "".join(p.get("text", "") for p in message["parts"] if p.get("kind") == "text")
            context_id = message.get("contextId") or str(uuid.uuid4())
            if self._is_down(text, str(message.get("messageId", ""))):
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": JSONRPC_AGENT_DOWN, "message": "agent unavailable"},
                    }
                )
            reply, is_slow = self._next_reply(text, context_id)
            if is_slow:
                await asyncio.sleep(
                    SLOW_REPLY_SECONDS if SLOW_MARKER in text else WRITER_REPLY_SECONDS
                )
            task: dict[str, Any] = {
                "kind": "task",
                "id": str(uuid.uuid4()),
                "contextId": context_id,
                "status": {"state": "completed"},
                "metadata": {"usage": SCRIPTED_USAGE},
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "parts": [{"kind": "text", "text": reply}],
                    }
                ],
            }
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": task})

        return app


def _report_of(message_text: str) -> str:
    """The report after the marker, line for line as the worker sent it."""
    report = message_text.split(REPORT_MARKER, 1)[-1]
    return report.removeprefix("\n")


def default_reply(message_text: str) -> Any:
    """What the scripted agent answers for the role whose prompt opens the message; an
    email draft when no role matches."""
    role = next((r for r in ROLES.values() if r.prompt in message_text), None)
    report = _report_of(message_text)
    match role.step_id if role else "email_writer":
        case "strategist":
            return {
                "audience": "Security leaders",
                "angle": "Act before attackers do",
                "key_messages": [_first_line(report)],
            }
        case "research":
            return {"facts": _facts(report)}
        case "landing_page":
            headline = _first_line(report)
            return {
                "headline": headline,
                "subheadline": "What it means for you",
                "body": report[:BODY_REPORT_CHARS],
                "call_to_action": "Read the full advisory",
            }
        case "social":
            return {
                "posts": [{"channel": "linkedin", "text": _first_line(report)[:SOCIAL_POST_CHARS]}]
            }
        case "one_pager":
            return {
                "title": _first_line(report),
                "summary": report[:BODY_REPORT_CHARS],
                "bullets": [_first_line(report)],
            }
        case _:
            return default_draft(message_text)


def _first_line(report: str) -> str:
    return next((line for line in report.splitlines() if line.strip()), "threat")


def _facts(report: str) -> list[dict[str, Any]]:
    """The first few non-blank lines of the report, each cited by its line number."""
    numbered = [(n, line) for n, line in enumerate(report.splitlines(), start=1) if line.strip()]
    return [
        {"claim": line.strip(), "line": n, "quote": line.strip()}
        for n, line in numbered[:MAX_SCRIPTED_FACTS]
    ] or [{"claim": "report", "line": 1, "quote": report.strip()[:50] or "report"}]


def default_draft(message_text: str) -> dict[str, str]:
    instructions = message_text.split(REPORT_MARKER, 1)[0]
    report = _report_of(message_text).strip()
    headline = report.splitlines()[0] if report else "threat"
    lead = "Before it hits you" if VARIANT_B_PHRASE in instructions else "Act now"
    return {
        "subject": f"{lead}: {headline[:SUBJECT_HEADLINE_CHARS]}",
        "preheader": "What the new threat means for you",
        "body": f"Hello,\n\nOur analysts found this: {report[:BODY_REPORT_CHARS]}\n\nStay safe.",
        "call_to_action": "Read the full advisory",
    }
