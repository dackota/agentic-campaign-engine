"""A scripted agent that speaks kagent's A2A contract (JSON-RPC `message/send`).

By default it answers like an email writer: it reads the threat report out of the
message and replies with a draft that fits the email contract. A test can queue
exact replies with `script()` to play a misbehaving agent.
"""

import json
import threading
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

REPORT_MARKER = "THREAT REPORT:"


class ScriptedAgent:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._replies: list[str] = []
        self.app = self._build_app()

    def script(self, replies: list[str]) -> None:
        """Queue exact reply texts; they are used before the default writer."""
        with self._lock:
            self._replies = list(replies)

    def _next_reply(self, text: str) -> str:
        with self._lock:
            if self._replies:
                return self._replies.pop(0)
        return json.dumps(default_draft(text))

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
                        "error": {"code": -32601, "message": "method not found"},
                    }
                )
            message = body["params"]["message"]
            text = "".join(p.get("text", "") for p in message["parts"] if p.get("kind") == "text")
            context_id = message.get("contextId") or str(uuid.uuid4())
            reply = self._next_reply(text)
            task: dict[str, Any] = {
                "kind": "task",
                "id": str(uuid.uuid4()),
                "contextId": context_id,
                "status": {"state": "completed"},
                "artifacts": [
                    {
                        "artifactId": str(uuid.uuid4()),
                        "parts": [{"kind": "text", "text": reply}],
                    }
                ],
            }
            return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": task})

        return app


def default_draft(message_text: str) -> dict[str, str]:
    report = message_text.split(REPORT_MARKER, 1)[-1].strip()
    headline = report.splitlines()[0] if report else "threat"
    return {
        "subject": f"Act now: {headline[:80]}",
        "preheader": "What the new threat means for you",
        "body": f"Hello,\n\nOur analysts found this: {report[:300]}\n\nStay safe.",
        "call_to_action": "Read the full advisory",
    }
