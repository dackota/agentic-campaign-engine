"""Seam 1 at fast depth: the campaign shows 'no decision yet' before the simulated audience
has engaged, and a winner with its confidence after enough events."""

import time
from typing import Any

import httpx

from tests.api.helpers import DAY_SPEED, send_campaign

SLOW_SPEED = 1.0
SEED = 1  # a seed whose audience opens variant A far more than B
SETTLE_SECONDS = 30
POLL_SECONDS = 0.2


def ab_result(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    body = api.get(f"/campaigns/{campaign_id}").json()
    result: dict[str, Any] = body["ab_result"]
    return result


def test_no_decision_yet_before_the_audience_engages(
    stack: Any, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=SLOW_SPEED)

    campaign_id = send_campaign(api, approver)

    assert ab_result(api, campaign_id) == {
        "status": "no_decision",
        "winner": None,
        "confidence": None,
    }


def test_a_winner_with_confidence_after_enough_events(
    stack: Any, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)
    campaign_id = send_campaign(api, approver)

    deadline = time.monotonic() + SETTLE_SECONDS
    result = ab_result(api, campaign_id)
    while result["status"] != "winner" and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        result = ab_result(api, campaign_id)

    assert result["status"] == "winner", result
    assert result["winner"] in {"A", "B"}
    assert 0.95 <= result["confidence"] <= 1.0
