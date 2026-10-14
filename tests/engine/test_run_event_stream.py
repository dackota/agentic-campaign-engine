"""The per-run event stream (server-sent events) of the Campaign API: events replay in order from
any point, the stream closes at a final state of the run, and each event carries what the run
view shows. The stream over a real socket is the API test's."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from ace_engine import db
from campaign_api.main import FINAL_STATES, _event_stream, _sse
from campaign_worker.activities import Activities
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.campaigns import add_campaign, add_run_event
from tests.support.dag import OWNER
from tests.support.settings import unit_settings

HEADERS = {"Authorization": f"Bearer {OWNER}"}
RUN = db.RUN_STEP
DRAFTING_STATES = [db.DRAFTING, db.RETRYING]
QUIET_SECONDS = 0.3


def _seed_a_run(engine: Engine, campaign_id: uuid.UUID) -> list[int]:
    steps = [
        ("email_draft", db.STEP_STARTED),
        ("email_draft", db.STEP_SUCCEEDED),
        ("judge", db.STEP_STARTED),
        ("judge", db.STEP_SUCCEEDED),
        (RUN, db.AWAITING_APPROVAL),
    ]
    return [add_run_event(engine, campaign_id, step, status) for step, status in steps]


def _stream(engine: Engine, campaign_id: uuid.UUID, after_seq: int = 0) -> list[dict[str, Any]]:
    async def collect() -> list[str]:
        return [chunk async for chunk in _event_stream(engine, campaign_id, after_seq)]

    return [_data(chunk) for chunk in asyncio.run(asyncio.wait_for(collect(), 5))]


def _data(chunk: str) -> dict[str, Any]:
    [line] = [x for x in chunk.splitlines() if x.startswith("data: ")]
    event: dict[str, Any] = json.loads(line.removeprefix("data: "))
    return event


def _read(
    client: TestClient,
    campaign_id: uuid.UUID,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
) -> list[dict[str, Any]]:
    url = f"/campaigns/{campaign_id}/events"
    with client.stream("GET", url, headers=headers, params=params) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(x[6:]) for x in response.iter_lines() if x.startswith("data: ")]


def test_the_stream_emits_step_events_in_order_and_ends_at_the_final_state(
    sqlite_engine: Engine,
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    seqs = _seed_a_run(sqlite_engine, campaign_id)

    events = _stream(sqlite_engine, campaign_id)

    assert [(e["step"], e["status"]) for e in events] == [
        ("email_draft", "started"),
        ("email_draft", "succeeded"),
        ("judge", "started"),
        ("judge", "succeeded"),
        ("run", "awaiting_approval"),
    ]
    assert [e["seq"] for e in events] == seqs
    assert seqs == sorted(seqs)


def test_the_stream_resumes_after_the_last_event_a_client_saw(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine)
    seqs = _seed_a_run(sqlite_engine, campaign_id)

    assert [e["seq"] for e in _stream(sqlite_engine, campaign_id, seqs[0])] == seqs[1:]
    assert [e["seq"] for e in _stream(sqlite_engine, campaign_id, seqs[-2])] == seqs[-1:]
    # An event that comes after the last one the client saw is the next it gets.
    add_run_event(sqlite_engine, campaign_id, RUN, db.SENT)
    assert [e["status"] for e in _stream(sqlite_engine, campaign_id, seqs[-1])] == [db.SENT]


@pytest.mark.parametrize("state", sorted(FINAL_STATES))
def test_the_stream_ends_at_each_final_state_of_a_run(sqlite_engine: Engine, state: str) -> None:
    campaign_id = add_campaign(sqlite_engine)
    add_run_event(sqlite_engine, campaign_id, "email_draft", db.STEP_STARTED)
    add_run_event(sqlite_engine, campaign_id, RUN, state)
    add_run_event(sqlite_engine, campaign_id, "ignored", "after the end")

    events = _stream(sqlite_engine, campaign_id)

    assert [(e["step"], e["status"]) for e in events] == [("email_draft", "started"), (RUN, state)]


@pytest.mark.parametrize("state", DRAFTING_STATES)
def test_a_run_that_goes_on_keeps_its_stream_open(sqlite_engine: Engine, state: str) -> None:
    campaign_id = add_campaign(sqlite_engine)
    add_run_event(sqlite_engine, campaign_id, RUN, state)

    async def read_past_the_last_event() -> None:
        stream = _event_stream(sqlite_engine, campaign_id, 0)
        assert _data(await anext(stream))["status"] == state
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(anext(stream), QUIET_SECONDS)

    asyncio.run(read_past_the_last_event())


def test_a_failed_run_ends_its_stream_with_the_reason_on_the_step_and_the_run(
    sqlite_engine: Engine,
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    reason = "reply broke the contract after one repair: 'preheader' is a required property"
    add_run_event(sqlite_engine, campaign_id, "email_draft", db.STEP_STARTED)
    add_run_event(sqlite_engine, campaign_id, "email_draft", db.STEP_FAILED, reason)
    add_run_event(sqlite_engine, campaign_id, RUN, db.FAILED, reason)

    events = _stream(sqlite_engine, campaign_id)

    assert [(e["step"], e["status"]) for e in events] == [
        ("email_draft", "started"),
        ("email_draft", "failed"),
        ("run", "failed"),
    ]
    assert "contract" in events[-1]["reason"]
    assert events[1]["reason"] == events[-1]["reason"]


def test_an_event_is_sent_in_the_server_sent_events_format(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine)
    seq = add_run_event(sqlite_engine, campaign_id, "writer", db.STEP_STARTED)

    [event] = db.events_after(sqlite_engine, campaign_id, 0)

    assert _sse(event) == (
        f"id: {seq}\nevent: step\n"
        f'data: {{"seq": {seq}, "step": "writer", "status": "started", "reason": null, '
        f'"session": null, "tokens": null}}\n\n'
    )


def test_the_route_resumes_from_the_later_of_last_event_id_and_after(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    seqs = _seed_a_run(sqlite_engine, campaign_id)

    everything = _read(app_client, campaign_id, headers=HEADERS)
    from_header = _read(app_client, campaign_id, headers={**HEADERS, "Last-Event-ID": str(seqs[0])})
    from_query = _read(app_client, campaign_id, headers=HEADERS, params={"after": seqs[2]})
    later_wins = _read(
        app_client,
        campaign_id,
        headers={**HEADERS, "Last-Event-ID": str(seqs[3])},
        params={"after": seqs[1]},
    )

    assert [e["seq"] for e in everything] == seqs
    assert from_header == everything[1:]
    assert [e["seq"] for e in from_query] == seqs[3:]
    assert [e["seq"] for e in later_wins] == seqs[4:]


def test_the_route_takes_the_token_as_a_query_parameter_for_a_browser(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    seqs = _seed_a_run(sqlite_engine, campaign_id)

    events = _read(app_client, campaign_id, params={"access_token": OWNER})

    assert [e["seq"] for e in events] == seqs


def test_the_stream_of_an_unknown_campaign_is_404(app_client: TestClient) -> None:
    unknown = uuid.uuid4()

    assert app_client.get(f"/campaigns/{unknown}/events", headers=HEADERS).status_code == 404
    assert (
        app_client.get(f"/campaigns/{unknown}/events", params={"access_token": OWNER}).status_code
        == 404
    )


def test_an_agent_steps_succeeded_event_carries_its_tokens_and_its_started_event_none(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    activities = Activities(unit_settings(), sqlite_engine)
    usage = {"model": "scripted-model", "input_tokens": 2400, "output_tokens": 600}

    activities.mark_step(str(campaign_id), "email_draft", db.STEP_STARTED)
    activities.save_agent_output(
        str(campaign_id), "email_draft", {"output": [{}, {}], "session": "s", "usage": usage}
    )
    activities.open_approval(str(campaign_id))
    events = _read(app_client, campaign_id, headers=HEADERS)

    started = next(e for e in events if e["status"] == "started")
    done = next(e for e in events if e["status"] == "succeeded")
    assert started["tokens"] is None
    assert done["tokens"] == 3000
    assert done["session"] == "s"


def test_a_step_that_reports_no_tokens_has_none_on_its_event(sqlite_engine: Engine) -> None:
    campaign_id = add_campaign(sqlite_engine)

    Activities(unit_settings(), sqlite_engine).save_agent_output(
        str(campaign_id), "email_draft", {"output": [{}, {}], "session": "s", "usage": None}
    )

    [event] = db.events_after(sqlite_engine, campaign_id, 0)
    assert event.tokens is None


def test_the_campaign_carries_the_edges_of_its_workflow(app_client: TestClient) -> None:
    edge = {"from": "brief", "to": "writer"}
    dag = {
        "steps": [{"id": "brief", "kind": "agent"}, {"id": "writer", "kind": "agent"}],
        "edges": [edge],
    }
    saved = app_client.post("/workflows/two-writers/versions", json=dag, headers=HEADERS)
    assert saved.status_code == 201, saved.text

    created = app_client.post(
        "/campaigns", json={"report": "a report", "workflow": "two-writers"}, headers=HEADERS
    )

    assert created.status_code == 201, created.text
    assert created.json()["edges"] == [edge]
    assert app_client.get(f"/campaigns/{created.json()['id']}", headers=HEADERS).json()[
        "edges"
    ] == [edge]
