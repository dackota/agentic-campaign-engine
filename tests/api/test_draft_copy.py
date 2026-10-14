"""Seam 1 at fast depth: the scripted agent's drafts read like finished copy."""

import json

import httpx
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.conftest import SignIn
from tests.api.helpers import AWAITING, create_on, until_status
from tests.harness.stack import Stack

# "[agent:flag]" sends every draft back through the brand reviewer's fix round.
FLAGGED_REPORT = (
    "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.\n[agent:flag]"
)
NOT_COPY = ("brand reviewer sent", "Fix these issues", "[agent:", "You are the")


def test_a_flagged_draft_holds_only_finished_copy(
    stack: Stack, api: httpx.Client, sign_in: SignIn
) -> None:
    stack.agent.script([])
    campaign_id = create_on(api, DEFAULT_WORKFLOW_NAME, FLAGGED_REPORT)["id"]
    campaign = until_status(api, campaign_id, AWAITING)

    items = [
        i
        for i in sign_in("dg-approver@demo.example").get("/inbox").json()
        if i["campaign_id"] == campaign_id
    ]
    drafts = [json.dumps(campaign["draft"]), *(json.dumps(i["output"]) for i in items)]

    assert items
    for text in drafts:
        for leaked in NOT_COPY:
            assert leaked not in text
    assert "Volt Typhoon" in drafts[0]
