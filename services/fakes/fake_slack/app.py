"""A fake Slack Web API, enough for `chat.postMessage`.

- `POST /chat.postMessage` takes a bearer token and a JSON body with `channel` and `text`.
  A wrong or missing token gets Slack's `{"ok": false, "error": "invalid_auth"}` with a 200,
  as the real API answers; a good one stores the message and returns `{"ok": true, "ts": ...}`.
- `GET /_messages` lists the stored messages so a test can read them from the outside. It
  never shows the token.
"""

import hmac
import threading
from dataclasses import dataclass
from typing import Any

from ace_engine import telemetry
from fastapi import FastAPI, Header
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class SlackConfig:
    token: str

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("fake Slack needs a token")


class Message(BaseModel):
    channel: str = Field(min_length=1)
    text: str = Field(min_length=1)


def create_app(config: SlackConfig) -> FastAPI:
    app = FastAPI(title="fake-slack")
    telemetry.instrument_app(app, "fake-slack")
    messages: list[dict[str, str]] = []
    lock = threading.Lock()

    @app.post("/chat.postMessage")
    def post_message(
        message: Message, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        expected = f"Bearer {config.token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            return {"ok": False, "error": "invalid_auth"}
        with lock:
            messages.append({"channel": message.channel, "text": message.text})
            return {"ok": True, "channel": message.channel, "ts": f"{len(messages)}.000000"}

    @app.get("/_messages")
    def list_messages() -> list[dict[str, str]]:
        with lock:
            return list(messages)

    return app
