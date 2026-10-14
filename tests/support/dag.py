"""Constants and builders the tests share: no stack, no network, nothing heavy to import."""

import hashlib
import hmac
import time
from typing import Any

REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."
GOOD_DRAFT = {
    "subject": "Patch your VPN today",
    "preheader": "Attackers are scanning for it",
    "body": "Hello, apply the fix now.",
    "call_to_action": "Patch now",
}
AWAITING = "awaiting_approval"
FAILED = "failed"
SENT = "sent"
FINISHED = "finished"
RETRYING = "retrying"
# Demo users from platform/dex/config.yaml.
OWNER = "dg-owner@demo.example"
APPROVER = "dg-approver@demo.example"


def step(step_id: str, kind: str, **extra: object) -> dict[str, Any]:
    return {"id": step_id, "kind": kind, **extra}


def edge(source: str, target: str) -> dict[str, str]:
    return {"from": source, "to": target}


# The smallest workflow that drafts, waits for a human, then publishes.
DRAFT_APPROVE_PUBLISH = {
    "steps": [step("draft", "agent"), step("approve", "approval"), step("publish", "publish")],
    "edges": [edge("draft", "approve"), edge("approve", "publish")],
}
# A workflow of one agent step: the step cache tests run it.
DRAFT_ONLY = {"steps": [step("draft", "agent")], "edges": []}

# Activity webhooks: the HMAC-SHA256 of "<timestamp>." + body, hex, in this header.
SIGNATURE_HEADER = "X-Marketo-Signature"
TIMESTAMP_HEADER = "X-Marketo-Timestamp"
WORKFRONT_SIGNATURE_HEADER = "X-Workfront-Signature"
WORKFRONT_TIMESTAMP_HEADER = "X-Workfront-Timestamp"


def _signed(
    signature_header: str, timestamp_header: str, secret: str, body: bytes, timestamp: int | None
) -> dict[str, str]:
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {
        timestamp_header: stamp,
        signature_header: f"sha256={digest.hexdigest()}",
        "Content-Type": "application/json",
    }


def signed_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Headers that sign `body` the way the fake Marketo signs its activity webhooks."""
    return _signed(SIGNATURE_HEADER, TIMESTAMP_HEADER, secret, body, timestamp)


def workfront_signed_headers(
    secret: str, body: bytes, timestamp: int | None = None
) -> dict[str, str]:
    """Headers that sign `body` the way the fake Workfront signs its status webhooks."""
    return _signed(WORKFRONT_SIGNATURE_HEADER, WORKFRONT_TIMESTAMP_HEADER, secret, body, timestamp)
