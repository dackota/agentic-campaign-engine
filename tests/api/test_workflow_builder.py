"""Seam 1 at fast depth: the routes behind the workflow builder. Validate gives the
same rejections as save without saving; saved versions are listed; steps keep their
retry and review-loop settings."""

import httpx

from tests.api.helpers import DRAFT_APPROVE_PUBLISH, edge, save_workflow, step, workflow_name

NO_APPROVAL = {
    "steps": [step("writer", "agent"), step("ship", "publish")],
    "edges": [edge("writer", "ship")],
}


def test_validate_returns_the_same_rejections_as_save(api: httpx.Client) -> None:
    name = workflow_name()

    checked = api.post("/workflows/validate", json=NO_APPROVAL)
    saved = api.post(f"/workflows/{name}/versions", json=NO_APPROVAL)

    assert saved.status_code == 422
    assert checked.status_code == 200, checked.text
    assert checked.json()["rejections"] == saved.json()["detail"]
    assert checked.json()["rejections"][0]["rule"] == "publish_without_approval"


def test_validate_returns_no_rejections_for_a_valid_workflow_and_saves_nothing(
    api: httpx.Client,
) -> None:
    checked = api.post("/workflows/validate", json=DRAFT_APPROVE_PUBLISH)

    assert checked.status_code == 200, checked.text
    assert checked.json() == {"rejections": []}


def test_versions_are_listed_newest_first(api: httpx.Client) -> None:
    name = workflow_name()
    save_workflow(api, name, DRAFT_APPROVE_PUBLISH)
    save_workflow(api, name, DRAFT_APPROVE_PUBLISH)

    listed = api.get(f"/workflows/{name}/versions")

    assert listed.status_code == 200, listed.text
    assert [v["version"] for v in listed.json()] == [2, 1]
    assert api.get(f"/workflows/{workflow_name()}/versions").json() == []


def test_a_saved_step_keeps_its_retry_and_review_settings(api: httpx.Client) -> None:
    name = workflow_name()
    dag = {
        "steps": [
            step("writer", "agent", max_attempts=5, review_rounds=2),
            step("ok", "approval"),
            step("ship", "publish"),
        ],
        "edges": [edge("writer", "ok"), edge("ok", "ship")],
    }

    save_workflow(api, name, dag)

    assert api.get(f"/workflows/{name}/versions/1").json()["dag"] == dag


def test_out_of_range_policy_is_rejected_in_plain_words(api: httpx.Client) -> None:
    dag = {
        "steps": [
            step("writer", "agent", max_attempts=0),
            step("ok", "approval"),
            step("ship", "publish"),
        ],
        "edges": [edge("writer", "ok"), edge("ok", "ship")],
    }

    response = api.post("/workflows/validate", json=dag)

    assert response.json()["rejections"][0]["rule"] == "invalid_shape"
    assert "max_attempts" in response.json()["rejections"][0]["message"]
