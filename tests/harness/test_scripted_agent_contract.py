"""The scripted agent speaks kagent 1.x's real A2A contract, as seen at live depth on k3d-ace:
JSON-RPC `SendMessage` with an `A2A-Version: 1.0` header, role `ROLE_USER`, parts that hold
only `text`, a reply in `result.task`, and a session (contextId) that only the agent issues."""

import json
import uuid
from typing import Any

from fastapi.testclient import TestClient

from tests.harness.scripted_agent import ScriptedAgent

A2A_HEADERS = {"A2A-Version": "1.0"}
USAGE_KEY = "kagent.dev/a2a/usage"
PERMISSION_DENIED = -31403
METHOD_NOT_FOUND = -32601


def send(client: TestClient, text: str, context_id: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if context_id is not None:
        message["contextId"] = context_id
    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": message}}
    response = client.post("/", json=body, headers=A2A_HEADERS)
    assert response.status_code == 200, response.text
    reply: dict[str, Any] = response.json()
    return reply


def test_send_message_answers_with_a_completed_task_that_holds_the_text() -> None:
    client = TestClient(ScriptedAgent().app)

    task = send(client, "Write an email.")["result"]["task"]

    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["contextId"]
    (artifact,) = task["artifacts"]
    assert "text" in artifact["parts"][0] and "kind" not in artifact["parts"][0]
    assert json.loads(artifact["parts"][0]["text"])["subject"]
    assert {"promptTokenCount", "candidatesTokenCount"} <= set(artifact["metadata"][USAGE_KEY])


def test_the_old_message_send_method_is_not_found() -> None:
    client = TestClient(ScriptedAgent().app)
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}}

    reply = client.post("/", json=body, headers=A2A_HEADERS).json()

    assert reply["error"]["code"] == METHOD_NOT_FOUND


def test_a_session_the_agent_did_not_issue_is_refused() -> None:
    client = TestClient(ScriptedAgent().app)

    reply = send(client, "Write an email.", context_id=str(uuid.uuid4()))

    assert reply["error"]["code"] == PERMISSION_DENIED


def test_a_session_the_agent_issued_can_be_reused() -> None:
    client = TestClient(ScriptedAgent().app)
    context_id = send(client, "Write an email.")["result"]["task"]["contextId"]

    again = send(client, "Again.", context_id=context_id)

    assert again["result"]["task"]["contextId"] == context_id


def test_a_request_without_the_version_header_is_refused() -> None:
    client = TestClient(ScriptedAgent().app)
    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {}}

    reply = client.post("/", json=body).json()

    assert "error" in reply
