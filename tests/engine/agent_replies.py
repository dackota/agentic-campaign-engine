"""A2A task replies a stand-in agent sends, for a test that drives the invoker."""

import json
from typing import Any

COMPLETED = "TASK_STATE_COMPLETED"
CONTEXT_ID = "session-1"


def task_reply(text: str | dict[str, Any], state: str = COMPLETED) -> dict[str, Any]:
    """A JSON-RPC `SendMessage` answer whose one artifact holds `text` (or the JSON of a dict)."""
    body = text if isinstance(text, str) else json.dumps(text)
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "task": {
                "contextId": CONTEXT_ID,
                "status": {"state": state},
                "artifacts": [{"parts": [{"text": body}]}],
            }
        },
    }
