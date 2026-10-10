"""A minimal fake Marketo: one send endpoint shaped like Marketo's REST API, plus a
`/_sends` view of what it delivered so a test can check the send from the outside.

A send is idempotent per `campaign_id`: repeating it returns the same receipt and does
not send again, so a retried engine step cannot double-send.
"""

import threading
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class SendRequest(BaseModel):
    campaign_id: str
    subject: str
    preheader: str
    body: str
    call_to_action: str


def create_app() -> FastAPI:
    lock = threading.Lock()
    sends: dict[str, dict[str, Any]] = {}
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/rest/v1/emails/send")
    def send(body: SendRequest) -> dict[str, Any]:
        with lock:
            record = sends.get(body.campaign_id)
            if record is None:
                record = {**body.model_dump(), "receipt": f"fake-marketo-{uuid.uuid4().hex[:12]}"}
                sends[body.campaign_id] = record
        return {"success": True, "result": [{"receiptId": record["receipt"], "status": "sent"}]}

    @app.get("/_sends")
    def list_sends() -> list[dict[str, Any]]:
        with lock:
            return list(sends.values())

    return app
