"""Seam 1 at fast depth: the fake Workfront speaks OAuth2 client credentials and holds
projects, tasks, and approvals. One approval creates one task for the campaign and the run
shows a receipt with a link to it. Read on the fake's own REST API."""

import httpx

from tests.api.helpers import (
    MARKETO_HTTP_TIMEOUT_SECONDS,
    SENT,
    WORKFRONT_API,
    WORKFRONT_TARGET,
    create,
    settle,
    until_status,
    workfront_client,
    workfront_tasks,
    workfront_token,
)
from tests.harness.stack import Stack


def test_token_route_issues_a_token_for_good_client_credentials(stack: Stack) -> None:
    response = workfront_token(
        stack.workfront_url, stack.workfront_client_id, stack.workfront_client_secret
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] > 0


def test_token_route_rejects_bad_client_credentials(stack: Stack) -> None:
    wrong_secret = workfront_token(stack.workfront_url, stack.workfront_client_id, "nope")
    wrong_client = workfront_token(
        stack.workfront_url, "someone-else", stack.workfront_client_secret
    )

    assert wrong_secret.status_code == 401
    assert wrong_client.status_code == 401
    assert "access_token" not in wrong_secret.text


def test_rest_calls_without_a_token_are_401(stack: Stack) -> None:
    base = f"{stack.workfront_url}{WORKFRONT_API}"
    headers = {"Authorization": "Bearer made-up"}

    for path in ("/proj/search", "/task/search", "/appr/search"):
        assert httpx.get(base + path, timeout=MARKETO_HTTP_TIMEOUT_SECONDS).status_code == 401
        bad = httpx.get(base + path, headers=headers, timeout=MARKETO_HTTP_TIMEOUT_SECONDS)
        assert bad.status_code == 401
    posted = httpx.post(base + "/task", json={"name": "x"}, timeout=MARKETO_HTTP_TIMEOUT_SECONDS)
    assert posted.status_code == 401


def test_fake_holds_a_project_a_task_and_an_approval(stack: Stack) -> None:
    with workfront_client(stack) as client:
        project = client.post("/proj", json={"name": "Q4", "externalID": "proj-1"}).json()["data"]
        again = client.post("/proj", json={"name": "Q4", "externalID": "proj-1"}).json()["data"]
        body = {"name": "Launch", "projectID": project["ID"], "externalID": "task-1"}
        task = client.post("/task", json=body).json()["data"]
        renamed = client.post("/task", json={**body, "name": "Launch v2"}).json()["data"]
        approval = client.post("/appr", json={"taskID": task["ID"]}).json()["data"]
        found = client.get("/task/search", params={"externalID": "task-1"}).json()["data"]
        approvals = client.get("/appr/search", params={"taskID": task["ID"]}).json()["data"]

    assert again["ID"] == project["ID"]
    assert renamed["ID"] == task["ID"]
    assert [t["name"] for t in found] == ["Launch v2"]
    assert found[0]["projectID"] == project["ID"]
    assert [a["ID"] for a in approvals] == [approval["ID"]]
    assert approvals[0]["status"] == "PENDING"


def test_approval_creates_one_task_and_the_run_shows_a_receipt_with_a_link(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202

    sent = until_status(api, campaign_id, SENT)

    [task] = workfront_tasks(stack, campaign_id)
    [receipt] = [r for r in sent["receipts"] if r["target"] == WORKFRONT_TARGET]
    assert receipt["receipt_id"] == task["ID"]
    assert receipt["url"].startswith(stack.workfront_url)
    assert task["ID"] in receipt["url"]
    with workfront_client(stack) as client:
        linked = client.get(f"/task/{task['ID']}")
        approvals = client.get("/appr/search", params={"taskID": task["ID"]}).json()["data"]
    assert linked.status_code == 200
    assert linked.json()["data"]["ID"] == task["ID"]
    assert len(approvals) == 1
