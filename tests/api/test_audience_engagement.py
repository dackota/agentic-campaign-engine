"""Seam 1 at fast depth: after a send, the fake Marketo's simulated audience opens and clicks.
The events come back by signed webhook and show per variant on the campaign. A winner is called
once enough opens come in, and it becomes a learning the team reads. A seed fixes the events and a
time speed squeezes days into seconds. The seed's determinism, the time speed's delay, the
webhook checks, the stats and the learning's content are proved lower: tests/fakes/,
tests/engine/test_ab_result_property.py and test_learnings_store.py."""

import time
from typing import Any

import httpx

from tests.api.helpers import DAY_SPEED, send_campaign
from tests.harness.stack import Stack

SEED = 1  # a seed whose audience opens variant A far more than B
DELIVERY_SECONDS = 20
POLL_SECONDS = 0.2


def counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for e in events:
        per = out.setdefault(e["variant"], {"opens": 0, "clicks": 0})
        per["opens" if e["type"] == "open" else "clicks"] += 1
    return out


def until_delivered(
    api: httpx.Client, campaign_id: str, expected: dict[str, dict[str, int]]
) -> dict[str, Any]:
    """The campaign once its engagement shows every planned open and click."""
    deadline = time.monotonic() + DELIVERY_SECONDS
    shown: dict[str, Any] = {}
    while time.monotonic() < deadline:
        shown = api.get(f"/campaigns/{campaign_id}").json()
        engagement = shown["engagement"]
        assert engagement is not None
        if all(
            engagement.get(v, {}).get(k) == n for v, c in expected.items() for k, n in c.items()
        ):
            return shown
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"engagement never reached {expected}; last: {shown.get('engagement')}")


def until_learned(api: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    """The learnings the team has from this campaign, once it has one."""
    deadline = time.monotonic() + DELIVERY_SECONDS
    found: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        response = api.get("/learnings")
        assert response.status_code == 200, response.text
        found = [item for item in response.json() if item["campaign_id"] == campaign_id]
        if found:
            return found
        time.sleep(POLL_SECONDS)
    return found


def test_campaign_shows_opens_and_clicks_per_variant(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)

    campaign_id = send_campaign(api, approver)
    expected = counts(stack.marketo_planned_events(campaign_id))
    campaign = until_delivered(api, campaign_id, expected)

    shown = campaign["engagement"]
    assert set(expected) == {"A", "B"}
    assert all(shown[v]["opens"] >= shown[v]["clicks"] for v in shown)
    assert sum(c["opens"] for c in shown.values()) > 0
    # Enough opens call a winner with its confidence ...
    result = campaign["ab_result"]
    assert result["status"] == "winner", result
    assert result["winner"] in {"A", "B"}
    assert 0.95 <= result["confidence"] <= 1.0
    # ... and the called winner is kept as the team's one learning.
    [learning] = until_learned(api, campaign_id)
    winning_email = campaign["draft"] if result["winner"] == "A" else campaign["variant_b"]
    assert learning["reason"].startswith(f"Variant {result['winner']} won")
    assert winning_email["subject"] in learning["text"]
    assert learning["metrics"]["winner"] == result["winner"]
