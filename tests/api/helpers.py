"""Helpers the Campaign API tests share: make a campaign, wait for it to reach a status."""

import time
import uuid
from typing import Any

import httpx

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
POLL_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.2


def create(api: httpx.Client, report: str = REPORT) -> dict[str, Any]:
    response = api.post("/campaigns", json={"report": report})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def until_status(api: httpx.Client, campaign_id: str, *wanted: str) -> dict[str, Any]:
    """Poll the campaign until its status is one of `wanted`; return it."""
    deadline = time.monotonic() + POLL_SECONDS
    campaign: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = api.get(f"/campaigns/{campaign_id}")
        assert response.status_code == 200, response.text
        campaign = response.json()
        if campaign["status"] in wanted:
            return campaign
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"campaign never reached {' or '.join(wanted)}; last: {campaign}")


def settle(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    """Wait until drafting ends: the run waits for approval or has failed."""
    return until_status(api, campaign_id, AWAITING, FAILED)


def workflow_name(prefix: str = "wf") -> str:
    """A fresh workflow name: the stack is shared by tests, so names must not collide."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def save_workflow(api: httpx.Client, name: str, dag: dict[str, Any]) -> dict[str, Any]:
    response = api.post(f"/workflows/{name}/versions", json=dag)
    assert response.status_code == 201, response.text
    saved: dict[str, Any] = response.json()
    return saved


def create_on(api: httpx.Client, workflow: str, report: str = REPORT) -> dict[str, Any]:
    response = api.post("/campaigns", json={"report": report, "workflow": workflow})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def step(step_id: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {"id": step_id, "kind": kind, **extra}


def edge(source: str, target: str) -> dict[str, str]:
    return {"from": source, "to": target}


# The smallest workflow that drafts, waits for a human, then publishes.
DRAFT_APPROVE_PUBLISH = {
    "steps": [step("draft", "agent"), step("approve", "approval"), step("publish", "publish")],
    "edges": [edge("draft", "approve"), edge("approve", "publish")],
}
