"""The routes behind the workflow builder, on the real Campaign API in-process: saved
workflow versions are numbered and read back, bad workflows get a 422 with named reasons, a
campaign runs the version it started with, and a campaign on no workflow runs the default."""

import json
from typing import Any

import httpx
import pytest
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME
from campaign_api.workflows import MAX_WORKFLOW_BYTES, seed_default_workflow
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.app import StubTemporal
from tests.support.dag import DRAFT_APPROVE_PUBLISH, edge, step

OWNER = {"Authorization": "Bearer dg-owner@demo.example"}
NAME = "my-workflow"
BAD_BODIES = {
    "not json": b"{not json",
    "too deep": b"[" * 100_000,
}
HUGE_STEPS = 5_000
NO_APPROVAL = {
    "steps": [step("writer", "agent"), step("ship", "publish")],
    "edges": [edge("writer", "ship")],
}


def _save(client: TestClient, name: str, dag: dict[str, Any]) -> httpx.Response:
    saved: httpx.Response = client.post(f"/workflows/{name}/versions", json=dag, headers=OWNER)
    return saved


def test_saving_a_valid_workflow_returns_201_with_its_version_number(
    app_client: TestClient,
) -> None:
    saved = _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)

    assert saved.status_code == 201, saved.text
    assert saved.json() == {"workflow": NAME, "version": 1, "dag": DRAFT_APPROVE_PUBLISH}


def test_each_save_adds_the_next_version_and_reads_back(app_client: TestClient) -> None:
    second = {
        "steps": [*DRAFT_APPROVE_PUBLISH["steps"], step("hold", "wait", duration_seconds=60)],
        "edges": [*DRAFT_APPROVE_PUBLISH["edges"], edge("publish", "hold")],
    }

    _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)
    assert _save(app_client, NAME, second).json()["version"] == 2

    first = app_client.get(f"/workflows/{NAME}/versions/1", headers=OWNER)
    assert first.status_code == 200, first.text
    assert first.json()["dag"] == DRAFT_APPROVE_PUBLISH
    assert app_client.get(f"/workflows/{NAME}/versions/2", headers=OWNER).json()["dag"] == second
    assert app_client.get(f"/workflows/{NAME}/versions/3", headers=OWNER).status_code == 404


def test_versions_are_listed_newest_first(app_client: TestClient) -> None:
    _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)
    _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)

    listed = app_client.get(f"/workflows/{NAME}/versions", headers=OWNER)

    assert listed.status_code == 200, listed.text
    assert [v["version"] for v in listed.json()] == [2, 1]
    assert app_client.get("/workflows/another/versions", headers=OWNER).json() == []


def test_a_saved_step_keeps_its_retry_and_review_settings(app_client: TestClient) -> None:
    dag = {
        "steps": [
            step("writer", "agent", max_attempts=5, review_rounds=2),
            step("ok", "approval"),
            step("ship", "publish"),
        ],
        "edges": [edge("writer", "ok"), edge("ok", "ship")],
    }

    _save(app_client, NAME, dag)

    assert app_client.get(f"/workflows/{NAME}/versions/1", headers=OWNER).json()["dag"] == dag


def test_saved_workflow_names_are_listed_with_the_seeded_default(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    seed_default_workflow(sqlite_engine)
    _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)

    listed = app_client.get("/workflows", headers=OWNER)

    assert listed.status_code == 200, listed.text
    assert NAME in listed.json()
    assert DEFAULT_WORKFLOW_NAME in listed.json()


def test_a_bad_workflow_gets_a_422_with_its_named_reason_and_is_not_saved(
    app_client: TestClient,
) -> None:
    saved = _save(app_client, NAME, NO_APPROVAL)

    assert saved.status_code == 422
    assert [r["rule"] for r in saved.json()["detail"]] == ["publish_without_approval"]
    assert app_client.get(f"/workflows/{NAME}/versions", headers=OWNER).json() == []


def test_validate_returns_the_same_rejections_as_save_and_saves_nothing(
    app_client: TestClient,
) -> None:
    checked = app_client.post("/workflows/validate", json=NO_APPROVAL, headers=OWNER)
    saved = _save(app_client, NAME, NO_APPROVAL)

    assert checked.status_code == 200, checked.text
    assert checked.json()["rejections"] == saved.json()["detail"]
    assert app_client.get(f"/workflows/{NAME}/versions", headers=OWNER).json() == []


def test_validate_returns_no_rejections_for_a_valid_workflow(app_client: TestClient) -> None:
    checked = app_client.post("/workflows/validate", json=DRAFT_APPROVE_PUBLISH, headers=OWNER)

    assert checked.status_code == 200, checked.text
    assert checked.json() == {"rejections": []}


@pytest.mark.parametrize("reason", sorted(BAD_BODIES))
def test_a_body_that_is_not_json_is_a_named_rejection(app_client: TestClient, reason: str) -> None:
    body = BAD_BODIES[reason]
    headers = {**OWNER, "content-type": "application/json"}

    saved = app_client.post(f"/workflows/{NAME}/versions", content=body, headers=headers)
    checked = app_client.post("/workflows/validate", content=body, headers=headers)

    assert saved.status_code == 422
    assert [r["rule"] for r in saved.json()["detail"]] == ["not_json"]
    assert [r["rule"] for r in checked.json()["rejections"]] == ["not_json"]


def test_a_body_over_the_size_limit_is_a_named_rejection(app_client: TestClient) -> None:
    body = json.dumps({"steps": [], "pad": "x" * MAX_WORKFLOW_BYTES}).encode()

    saved = app_client.post(
        f"/workflows/{NAME}/versions",
        content=body,
        headers={**OWNER, "content-type": "application/json"},
    )

    assert saved.status_code == 422
    assert [r["rule"] for r in saved.json()["detail"]] == ["too_large"]


def test_a_workflow_of_thousands_of_steps_is_answered_never_a_server_error(
    app_client: TestClient,
) -> None:
    huge = {"steps": [step(f"s{i}", "agent") for i in range(HUGE_STEPS)], "edges": []}

    saved = _save(app_client, NAME, huge)

    assert saved.status_code in (201, 422), saved.text[:200]


def test_a_bad_workflow_name_is_rejected(app_client: TestClient) -> None:
    saved = app_client.post(
        "/workflows/Not A Name!/versions", json=DRAFT_APPROVE_PUBLISH, headers=OWNER
    )

    assert saved.status_code == 422


def _create(client: TestClient, workflow: str | None) -> httpx.Response:
    body: dict[str, Any] = {"report": "A threat report"}
    if workflow is not None:
        body["workflow"] = workflow
    created: httpx.Response = client.post("/campaigns", json=body, headers=OWNER)
    return created


def test_a_run_keeps_version_1_after_version_2_is_saved(
    app_client: TestClient, temporal: StubTemporal
) -> None:
    version_2 = {
        "steps": [
            step("w1", "agent"),
            step("ok", "approval"),
            step("hold", "wait", duration_seconds=5),
            step("ship", "publish"),
        ],
        "edges": [edge("w1", "ok"), edge("ok", "hold"), edge("hold", "ship")],
    }
    _save(app_client, NAME, DRAFT_APPROVE_PUBLISH)
    created = _create(app_client, NAME).json()

    assert _save(app_client, NAME, version_2).json()["version"] == 2

    read = app_client.get(f"/campaigns/{created['id']}", headers=OWNER).json()
    assert (read["workflow"], read["workflow_version"]) == (NAME, 1)
    assert [s["id"] for s in read["steps"]] == ["draft", "approve", "publish"]
    [started] = temporal.started
    assert started["args"] == [created["id"], "A threat report", DRAFT_APPROVE_PUBLISH]
    newer = _create(app_client, NAME).json()
    assert (newer["workflow_version"], [s["id"] for s in newer["steps"]]) == (
        2,
        ["w1", "ok", "hold", "ship"],
    )


def test_a_campaign_without_a_workflow_uses_the_default_dag(app_client: TestClient) -> None:
    created = _create(app_client, None).json()

    assert created["workflow"] is None and created["workflow_version"] is None
    assert [(s["id"], s["kind"]) for s in created["steps"]] == [
        ("email_draft", "agent"),
        ("judge", "agent"),
        ("approval", "approval"),
        ("publish", "publish"),
    ]


def test_a_campaign_on_an_unknown_workflow_is_rejected(
    app_client: TestClient, temporal: StubTemporal
) -> None:
    response = _create(app_client, "nope-x")

    assert response.status_code == 422
    assert "workflow 'nope-x' has no saved version" in response.text
    assert temporal.started == []
