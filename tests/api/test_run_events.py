"""Seam 1 at fast depth: the per-run event stream (server-sent events) of the Campaign API."""

import json
import uuid

import httpx

from tests.api.helpers import GOOD_DRAFT, create, read_events
from tests.harness.stack import Stack


def test_stream_emits_step_events_in_order_ending_in_final_state(api: httpx.Client) -> None:
    events = read_events(api, create(api)["id"])

    steps = [(e["step"], e["status"]) for e in events]
    assert steps == [
        ("email_draft", "started"),
        ("email_draft", "succeeded"),
        ("run", "awaiting_approval"),
    ]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


def test_bad_json_twice_ends_stream_in_failed_with_reason(stack: Stack, api: httpx.Client) -> None:
    stack.agent.script(["not json at all", "{still not json"])

    events = read_events(api, create(api)["id"])

    steps = [(e["step"], e["status"]) for e in events]
    assert steps == [
        ("email_draft", "started"),
        ("email_draft", "failed"),
        ("run", "failed"),
    ]
    assert "contract" in events[-1]["reason"]
    assert events[1]["reason"] == events[-1]["reason"]


def test_stream_resumes_after_last_event_id(stack: Stack, api: httpx.Client) -> None:
    stack.agent.script([json.dumps(GOOD_DRAFT)])
    campaign_id = create(api)["id"]
    everything = read_events(api, campaign_id)

    rest = read_events(api, campaign_id, last_event_id=everything[0]["seq"])

    assert rest == everything[1:]


def test_unknown_campaign_stream_is_404(api: httpx.Client) -> None:
    assert api.get(f"/campaigns/{uuid.uuid4()}/events").status_code == 404
