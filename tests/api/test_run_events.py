"""Seam 1 at fast depth: the per-run event stream (server-sent events) of the Campaign API,
read over a real socket as the browser reads it. Replay, the final states, the event format
and the 404 are proved in tests/engine/test_run_event_stream.py."""

import httpx

from tests.api.helpers import create, read_events


def test_stream_emits_step_events_in_order_ending_in_final_state(api: httpx.Client) -> None:
    events = read_events(api, create(api)["id"])

    steps = [(e["step"], e["status"]) for e in events]
    assert steps == [
        ("email_draft", "started"),
        ("email_draft", "succeeded"),
        ("judge", "started"),
        ("judge", "succeeded"),
        ("email_draft", "scored"),
        ("run", "awaiting_approval"),
    ]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
