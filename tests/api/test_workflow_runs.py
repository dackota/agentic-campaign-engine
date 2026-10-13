"""Seam 1 at fast depth: a campaign runs the saved workflow (a DAG of steps) it started
with. The engine follows the DAG, and a newer workflow version never changes a run."""

from typing import Any

import httpx

from tests.api.helpers import (
    AWAITING,
    DRAFT_APPROVE_PUBLISH,
    FAILED,
    REPORT,
    SENT,
    create,
    create_on,
    edge,
    read_events,
    save_workflow,
    step,
    until_status,
    workflow_name,
)

FINISHED = "finished"


def step_ids(campaign: dict[str, Any]) -> list[str]:
    return [s["id"] for s in campaign["steps"]]


def events_after(api: httpx.Client, campaign_id: str, seq: int) -> list[dict[str, Any]]:
    return read_events(api, campaign_id, last_event_id=seq)


def seq_of(events: list[dict[str, Any]], step_id: str, status: str) -> int:
    matches: list[int] = [
        e["seq"] for e in events if e["step"] == step_id and e["status"] == status
    ]
    assert len(matches) == 1, (step_id, status, events)
    return matches[0]


def test_run_pins_version_1_after_version_2_is_saved(
    api: httpx.Client, approver: httpx.Client
) -> None:
    name = workflow_name()
    save_workflow(api, name, DRAFT_APPROVE_PUBLISH)
    campaign_id = create_on(api, name)["id"]
    waiting = until_status(api, campaign_id, AWAITING)
    version_2 = {
        "steps": [
            step("w1", "agent"),
            step("ok", "approval"),
            step("hold", "wait", duration_seconds=5),
            step("ship", "publish"),
        ],
        "edges": [edge("w1", "ok"), edge("ok", "hold"), edge("hold", "ship")],
    }

    assert save_workflow(api, name, version_2)["version"] == 2
    first_part = read_events(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)
    rest = events_after(api, campaign_id, first_part[-1]["seq"])

    assert waiting["workflow"] == name and waiting["workflow_version"] == 1
    assert sent["workflow_version"] == 1
    assert step_ids(sent) == ["draft", "approve", "publish"]
    assert sent["receipt"]
    ran = {e["step"] for e in first_part + rest} - {"run"}
    assert ran == {"draft", "approve", "publish"}
    assert (rest[-1]["step"], rest[-1]["status"]) == ("run", SENT)


def test_engine_runs_parallel_writers_wait_approval_and_publish_in_dag_order(
    api: httpx.Client,
    approver: httpx.Client,
) -> None:
    name = workflow_name()
    dag = {
        "steps": [
            step("brief", "agent"),
            step("writer_a", "agent"),
            step("writer_b", "agent"),
            step("preview", "render"),
            step("approve", "approval"),
            step("cool_off", "wait", duration_seconds=1),
            step("publish", "publish"),
        ],
        "edges": [
            edge("brief", "writer_a"),
            edge("brief", "writer_b"),
            edge("writer_a", "preview"),
            edge("writer_b", "preview"),
            edge("preview", "approve"),
            edge("approve", "cool_off"),
            edge("cool_off", "publish"),
        ],
    }
    save_workflow(api, name, dag)
    created = create_on(api, name)
    campaign_id = created["id"]

    first_part = read_events(api, campaign_id)
    assert first_part[-1]["status"] == AWAITING
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    sent = until_status(api, campaign_id, SENT)
    events = first_part + events_after(api, campaign_id, first_part[-1]["seq"])

    assert step_ids(created)[0] == "brief" and step_ids(created)[-1] == "publish"
    assert step_ids(created).index("preview") > step_ids(created).index("writer_b")
    for source, target in [(e["from"], e["to"]) for e in dag["edges"]]:
        assert seq_of(events, source, "succeeded") < seq_of(events, target, "succeeded")
    for writer in ("writer_a", "writer_b"):
        assert seq_of(events, writer, "started") < seq_of(events, "preview", "succeeded")
    assert sent["receipt"] and sent["draft"]["subject"]
    assert events[-1]["step"] == "run" and events[-1]["status"] == SENT


def test_dag_without_approval_or_publish_finishes(api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(
        api,
        name,
        {"steps": [step("draft", "agent"), step("pdf", "render")], "edges": [edge("draft", "pdf")]},
    )
    campaign_id = create_on(api, name)["id"]

    events = read_events(api, campaign_id)
    done = until_status(api, campaign_id, FINISHED)

    assert done["draft"]["subject"]
    assert done["receipt"] is None
    assert [(e["step"], e["status"]) for e in events][-1] == ("run", FINISHED)


def test_campaign_without_workflow_uses_the_default_dag(api: httpx.Client) -> None:
    created = create(api)

    assert created["workflow"] is None and created["workflow_version"] is None
    assert [(s["id"], s["kind"]) for s in created["steps"]] == [
        ("email_draft", "agent"),
        ("judge", "agent"),
        ("approval", "approval"),
        ("publish", "publish"),
    ]


def test_campaign_on_unknown_workflow_is_rejected(api: httpx.Client) -> None:
    response = api.post("/campaigns", json={"report": "x", "workflow": workflow_name("nope")})

    assert response.status_code == 422
    assert "workflow" in response.text


def test_failed_agent_step_stops_run_while_approval_waits_in_same_wave(
    api: httpx.Client,
) -> None:
    name = workflow_name()
    save_workflow(
        api,
        name,
        {"steps": [step("writer", "agent"), step("ok", "approval")], "edges": []},
    )
    # The marker breaks this campaign's own agent session only, so no other run can take
    # the broken replies the way a shared script queue allows.
    campaign_id = create_on(api, name, f"{REPORT}\n[agent:bad-json]")["id"]
    failed = until_status(api, campaign_id, FAILED)

    assert failed["status"] == FAILED
    assert failed["failure_reason"]
