"""Seam 1 at fast depth: after a send, the fake Marketo's simulated audience opens and
clicks. The events come back by signed webhook and show per variant on the campaign. A
seed fixes the events; a time speed squeezes days into seconds."""

import time
from typing import Any

import httpx

from tests.api.helpers import DAY_SPEED, send_campaign
from tests.harness.stack import Stack

SEED = 4747
DELIVERY_SECONDS = 20
POLL_SECONDS = 0.2
SECONDS_PER_DAY = 86_400


def planned(stack: Stack, campaign_id: str) -> list[dict[str, Any]]:
    return stack.marketo_planned_events(campaign_id)


def shape(events: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(e["persona"], e["type"], e["variant"], e["at_seconds"]) for e in events]


def until_delivered(
    api: httpx.Client, campaign_id: str, expected: dict[str, dict[str, int]]
) -> dict[str, dict[str, int]]:
    deadline = time.monotonic() + DELIVERY_SECONDS
    shown: dict[str, dict[str, int]] | None = None
    while time.monotonic() < deadline:
        shown = api.get(f"/campaigns/{campaign_id}").json()["engagement"]
        assert shown is not None
        if all(shown.get(v, {}).get(k) == n for v, c in expected.items() for k, n in c.items()):
            return shown
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"engagement never reached {expected}; last: {shown}")


def counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for e in events:
        per = out.setdefault(e["variant"], {"opens": 0, "clicks": 0})
        per["opens" if e["type"] == "open" else "clicks"] += 1
    return out


def test_same_seed_gives_the_same_events_for_two_sends(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)

    first = send_campaign(api, approver)
    second = send_campaign(api, approver)

    assert planned(stack, first)
    assert shape(planned(stack, first)) == shape(planned(stack, second))


def test_high_time_speed_delivers_days_of_engagement_in_seconds(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)
    started = time.monotonic()

    campaign_id = send_campaign(api, approver)
    events = planned(stack, campaign_id)
    assert max(e["at_seconds"] for e in events) > SECONDS_PER_DAY
    until_delivered(api, campaign_id, counts(events))

    assert time.monotonic() - started < DELIVERY_SECONDS


def test_campaign_shows_opens_and_clicks_per_variant(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)

    campaign_id = send_campaign(api, approver)
    expected = counts(planned(stack, campaign_id))
    shown = until_delivered(api, campaign_id, expected)

    assert set(expected) == {"A", "B"}
    assert all(shown[v]["opens"] >= shown[v]["clicks"] for v in shown)
    assert sum(c["opens"] for c in shown.values()) > 0
