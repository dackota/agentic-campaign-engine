"""One campaign through the Campaign API: create it on the seeded workflow with the step cache
on, and wait until drafting ends. The runner and the judge-agreement check share it."""

import time
from typing import Any

import httpx

# The seeded workflow every deployment has (ace_engine.default_workflow).
WORKFLOW = "threat-report-to-campaign"
AWAITING = "awaiting_approval"
FAILED = "failed"
POLL_INTERVAL_SECONDS = 0.5


def wait_for(api: httpx.Client, campaign_id: str, timeout: float) -> dict[str, Any]:
    """Poll until drafting ends; the last campaign body seen if it never does."""
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {"status": "unknown"}
    while time.monotonic() < deadline:
        response = api.get(f"/campaigns/{campaign_id}")
        response.raise_for_status()
        body = response.json()
        if body["status"] in (AWAITING, FAILED):
            return body
        time.sleep(POLL_INTERVAL_SECONDS)
    return body


def create_and_wait(api: httpx.Client, report: str, timeout: float) -> tuple[str, dict[str, Any]]:
    """The new campaign's id and its body once drafting ends. Raises httpx.HTTPError."""
    created = api.post(
        "/campaigns", json={"report": report, "workflow": WORKFLOW, "use_step_cache": True}
    )
    created.raise_for_status()
    campaign_id = str(created.json()["id"])
    return campaign_id, wait_for(api, campaign_id, timeout)
