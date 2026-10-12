"""Seam 1 at fast depth: the default workflow's design step returns a fixed card pair from
the scripted agent, and the engine (not the agent) saves both cards to the asset library."""

from typing import Any

import httpx

from tests.api.helpers import AWAITING, bucket_keys, create_on, read_events, receipts
from tests.harness.stack import Stack

CARD_COUNT = 2
CARD_NAMES = ("social-card-1.svg", "social-card-2.svg")
REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."


def run_to_approval(api: httpx.Client) -> str:
    campaign = create_on(api, "threat-report-to-campaign", REPORT)
    events = read_events(api, campaign["id"])
    assert events[-1]["status"] == AWAITING, events
    return str(campaign["id"])


def card_receipts(api: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    return [r for r in receipts(api, campaign_id) if r["target"].startswith("cards/")]


def test_scripted_design_step_returns_a_fixed_card(api: httpx.Client) -> None:
    first = run_to_approval(api)
    second = run_to_approval(api)

    outputs = []
    for campaign_id in (first, second):
        steps = {s["step"]: s for s in api.get(f"/campaigns/{campaign_id}/steps").json()}
        outputs.append(steps["design"]["output"])

    assert outputs[0] == outputs[1]
    assert [c["name"] for c in outputs[0]["cards"]] == list(CARD_NAMES)
    assert all(c["svg"].startswith("<svg") for c in outputs[0]["cards"])


def test_design_step_returns_two_cards(api: httpx.Client) -> None:
    campaign_id = run_to_approval(api)

    steps = {s["step"]: s for s in api.get(f"/campaigns/{campaign_id}/steps").json()}

    assert len(steps["design"]["output"]["cards"]) == CARD_COUNT


def test_engine_saves_both_cards_to_the_asset_library(stack: Stack, api: httpx.Client) -> None:
    campaign_id = run_to_approval(api)

    keys = bucket_keys(stack, f"cards/{campaign_id}/")
    items = card_receipts(api, campaign_id)

    assert sorted(keys) == sorted(f"cards/{campaign_id}/{n}" for n in CARD_NAMES)
    assert sorted(i["target"] for i in items) == sorted(f"cards/{n}" for n in CARD_NAMES)
    for item in items:
        stored = httpx.get(item["url"], timeout=10)
        assert stored.status_code == 200, item
        assert stored.text.startswith("<svg")


def test_a_retried_save_adds_no_second_card(stack: Stack, api: httpx.Client) -> None:
    stack.drop_next_content_replies()  # each store keeps the first write, answers 503

    campaign_id = run_to_approval(api)

    assert len(bucket_keys(stack, f"cards/{campaign_id}/")) == CARD_COUNT
    assert len(card_receipts(api, campaign_id)) == CARD_COUNT
