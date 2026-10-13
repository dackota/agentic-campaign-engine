"""A scripted agent for fast depth: a stand-in for kagent 1.x's A2A JSON-RPC endpoint.

It speaks the contract the kagent controller serves at /agents/<namespace>/<agent>, as
seen on k3d-ace: `SendMessage` with an `A2A-Version: 1.0` header, role `ROLE_USER`, parts
that hold only `text`, a reply in `result.task` (state `TASK_STATE_COMPLETED`, text in
`artifacts[].parts[]`, tokens in the artifact's `kagent.dev/a2a/usage`), and a session
(contextId) that only the agent issues: a message that names another one is refused.

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

from ace_engine import telemetry
from ace_engine.agent_roles import ROLES
from ace_engine.brand_review import BRAND_REVIEWER
from ace_engine.contracts import REPORT_MARKER
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_PERMISSION_DENIED = -31403
JSONRPC_INVALID_REQUEST = -32600
SEND_METHOD = "SendMessage"
VERSION_HEADER = "A2A-Version"
SUPPORTED_VERSION = "1.0"
COMPLETED = "TASK_STATE_COMPLETED"
USAGE_KEY = "kagent.dev/a2a/usage"
PART_TYPE_KEY = "kagent.dev/a2a/part-type"
SUBJECT_HEADLINE_CHARS = 80
BODY_REPORT_CHARS = 300
SOCIAL_POST_CHARS = 280
# Markers in a threat report steer the default writer, so a browser test can pick a
# behaviour without access to the agent: hold the reply, or reply with broken JSON.
SLOW_MARKER = "[agent:slow]"
BAD_JSON_MARKER = "[agent:bad-json]"
# "[agent:flag]" in a report makes the brand reviewer always ask for a fix, so every writer's
# draft ends up flagged for a human.
FLAG_MARKER = "[agent:flag]"
FLAG_ISSUE = {"check": "banned_claim", "detail": "100% protection is a banned claim"}
SLOW_REPLY_SECONDS = 1.5
# "[agent:down-N]" in a report makes the first N calls that carry that report answer with
# an A2A error, so a step fails on cue and a later attempt succeeds.
DOWN_MARKER = re.compile(r"\[agent:down-(\d{1,2})\]")
JSONRPC_AGENT_DOWN = -32000
# "[agent:task-failed-N]" makes the first N calls on that report answer as kagent does when
# the model call fails: a task in state TASK_STATE_FAILED whose status message holds the error.
TASK_FAILED_MARKER = re.compile(r"\[agent:task-failed-(\d{1,2})\]")
TASK_FAILED = "TASK_STATE_FAILED"
TASK_FAILED_TEXT = (
    'llm error response (code STREAM_ERROR): "POST \\"http://agentgateway/v1/chat/completions'
    '\\": 429 Too Many Requests "'
)
# The worker asks for the A/B test's second email with this phrase in its prompt.
VARIANT_B_PHRASE = "variant B"
# A step that works from earlier steps' output (a writer) takes this long to answer, so
# writers that start together are still running together.
WRITER_REPLY_SECONDS = 0.5
CONTEXT_MARKER = "OUTPUT OF "
MAX_SCRIPTED_FACTS = 3
SERVICE = "scripted-agent"
# The design step's answer: the same two cards for every report.
FIXED_CARDS = tuple(
    {
        "name": f"social-card-{n}.svg",
        "svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630">'
            f'<rect width="1200" height="630" fill="#0b5fff"/><text x="80" y="330" '
            f'fill="#fff" font-size="56">Scripted card {n}</text></svg>'
        ),
    }
    for n in (1, 2)
)
# The version on the agent card until a test publishes another.
DEFAULT_REVISION = "1"
# A report with this marker makes the design step reply with a program (the live-depth shape)
# instead of cards, so the engine runs it in the sandbox.
PROGRAM_MARKER = "DESIGN-BY-PROGRAM"
DESIGN_PROGRAM = (
    'for n in 1 2; do printf \'<svg width="1200" height="630"/>\' > /tmp/c$n.svg; '
    "echo \"CARD $n $(base64 < /tmp/c$n.svg | tr -d '\\n')\"; done"
)
TOOL_NAME = "read_report"
# The research agent reads the campaign's Workfront project through MCP before it answers.
RESEARCH_TOOL = "get_project"

# Every reply carries token usage on the A2A task, the way the ADR in
# docs/decisions/token-usage-per-campaign.md reads it. "[agent:usage-IN-OUT]" in a report
# sets the numbers for each reply on that report; the default applies otherwise.
SCRIPTED_MODEL = "scripted-model"
USAGE_MARKER = re.compile(r"\[agent:usage-(\d{1,7})-(\d{1,7})\]")
# "[agent:usage-total-N]" reports only a total, as some harnesses do (Google ADK's
# totalTokenCount with no split).
TOTAL_USAGE_MARKER = re.compile(r"\[agent:usage-total-(\d{1,7})\]")
DEFAULT_INPUT_TOKENS = 1000
DEFAULT_OUTPUT_TOKENS = 500


class ScriptedAgent:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._replies: list[str] = []
        self._modes: dict[str, str] = {}
        self._failed: dict[str, int] = {}
        self._message_ids: list[str] = []
        self._texts: list[str] = []
        self._sessions: set[str] = set()
        self._revision = DEFAULT_REVISION
        self.app = self._build_app()

    def script(self, replies: list[str]) -> None:
        """Queue exact reply texts; they are used before the default writer."""
        with self._lock:
            self._replies = list(replies)

    def set_revision(self, revision: str) -> None:
        """Publish a new agent revision: the agent card's version changes, as it does when
        the Agent resource is updated."""
        with self._lock:
            self._revision = revision

    def card(self) -> dict[str, Any]:
        with self._lock:
            return {"name": SERVICE, "version": self._revision, "skills": []}

    def message_ids(self) -> list[str]:
        """The A2A messageId of every call so far, in arrival order."""
        with self._lock:
            return list(self._message_ids)

    def messages(self) -> list[str]:
        """The text of every message so far, in arrival order."""
        with self._lock:
            return list(self._texts)

    def _is_down(self, text: str, message_id: str) -> bool:
        """Record the call; True when it must fail because its report says the agent is down."""
        with self._lock:
            self._message_ids.append(message_id)
            self._texts.append(text)
        return self._fails_on_cue(DOWN_MARKER, text)

    def _fails_on_cue(self, marker: re.Pattern[str], text: str) -> bool:
        """True for the first N calls on a report that carries `marker` with count N."""
        report = text.split(REPORT_MARKER, 1)[-1]
        key = f"{marker.pattern}|{report}"
        with self._lock:
            found = marker.search(report)
            if found is None or self._failed.get(key, 0) >= int(found.group(1)):
                return False
            self._failed[key] = self._failed.get(key, 0) + 1
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

    def _owns(self, context_id: str) -> bool:
        with self._lock:
            return context_id in self._sessions

    def _open_session(self) -> str:
        context_id = str(uuid.uuid4())
        with self._lock:
            self._sessions.add(context_id)
        return context_id

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        telemetry.instrument_app(app, SERVICE)

        @app.get("/readyz")
        def readyz() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/.well-known/agent-card.json")
        def agent_card() -> dict[str, Any]:
            return self.card()

        @app.post("/")
        async def rpc(request: Request) -> JSONResponse:
            body = await request.json()
            if request.headers.get(VERSION_HEADER) != SUPPORTED_VERSION:
                return _error(body, JSONRPC_INVALID_REQUEST, "unsupported A2A version")
            if body.get("method") != SEND_METHOD:
                return _error(body, JSONRPC_METHOD_NOT_FOUND, "method not found")
            message = body["params"]["message"]
            text = "".join(p.get("text", "") for p in message["parts"])
            requested = message.get("contextId")
            if requested is not None and not self._owns(requested):
                return _error(body, JSONRPC_PERMISSION_DENIED, "permission denied")
            context_id = requested or self._open_session()
            if self._is_down(text, str(message.get("messageId", ""))):
                return _error(body, JSONRPC_AGENT_DOWN, "agent unavailable")
            if self._fails_on_cue(TASK_FAILED_MARKER, text):
                return _failed_task(body, context_id)
            reply, is_slow = self._next_reply(text, context_id)
            _export_tool_and_model_spans()
            if is_slow:
                await asyncio.sleep(
                    SLOW_REPLY_SECONDS if SLOW_MARKER in text else WRITER_REPLY_SECONDS
                )
            return _completed_task(body, context_id, text, reply)

        return app


def _completed_task(body: dict[str, Any], context_id: str, text: str, reply: str) -> JSONResponse:
    tools = (
        _tool_call_parts(RESEARCH_TOOL, {"project_id": "demo"})
        if ROLES["research"].prompt in text
        else []
    )
    artifact: dict[str, Any] = {
        "artifactId": str(uuid.uuid4()),
        "parts": [*tools, {"text": reply}],
        "metadata": {USAGE_KEY: scripted_usage(text)},
    }
    task: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "contextId": context_id,
        "status": {"state": COMPLETED},
        "artifacts": [artifact],
    }
    return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"task": task}})


def _failed_task(body: dict[str, Any], context_id: str) -> JSONResponse:
    status = {
        "state": TASK_FAILED,
        "message": {"role": "ROLE_AGENT", "parts": [{"text": TASK_FAILED_TEXT}]},
    }
    task = {"id": str(uuid.uuid4()), "contextId": context_id, "status": status}
    return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"task": task}})


def _error(body: dict[str, Any], code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": code, "message": message}}
    )


def _tool_call_parts(name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """One tool call and its result, as kagent alpha9 puts them in the reply's artifact before
    the text (seen live on k3d-ace, 2026-10-12)."""
    call_id = str(uuid.uuid4())
    return [
        {
            "data": {"id": call_id, "name": name, "args": args},
            "metadata": {PART_TYPE_KEY: "function_call"},
        },
        {
            "data": {"id": call_id, "name": name, "response": {"output": "{}"}},
            "metadata": {PART_TYPE_KEY: "function_response"},
        },
    ]


def _export_tool_and_model_spans() -> None:
    """What kagent exports on a real run: a tool call and a model call, as children of the
    request that carries the caller's trace context."""
    for operation, name in (("execute_tool", TOOL_NAME), ("chat", SCRIPTED_MODEL)):
        with telemetry.span(SERVICE, f"{operation} {name}", operation=operation):
            pass


def scripted_usage(message_text: str) -> dict[str, Any]:
    """The token usage a reply reports: the report's usage marker, else the default."""
    total = TOTAL_USAGE_MARKER.search(message_text)
    if total:
        return {"model": SCRIPTED_MODEL, "totalTokenCount": int(total.group(1))}
    found = USAGE_MARKER.search(message_text)
    input_tokens, output_tokens = (
        (int(found.group(1)), int(found.group(2)))
        if found
        else (DEFAULT_INPUT_TOKENS, DEFAULT_OUTPUT_TOKENS)
    )
    return {
        "model": SCRIPTED_MODEL,
        "promptTokenCount": input_tokens,
        "candidatesTokenCount": output_tokens,
    }


def _report_of(message_text: str) -> str:
    """The report after the marker, line for line as the worker sent it."""
    report = message_text.split(REPORT_MARKER, 1)[-1]
    return report.removeprefix("\n")


def default_reply(message_text: str) -> dict[str, Any]:
    """What the scripted agent answers for the role whose prompt opens the message; an
    email draft when no role matches."""
    if BRAND_REVIEWER.prompt in message_text:
        if FLAG_MARKER in _report_of(message_text):
            return {"verdict": "fix", "issues": [FLAG_ISSUE]}
        return {"verdict": "pass", "issues": []}
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
        case "design":
            if PROGRAM_MARKER in message_text:
                return {"program": DESIGN_PROGRAM}
            return {"cards": list(FIXED_CARDS)}
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
