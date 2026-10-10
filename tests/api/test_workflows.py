"""Seam 1 at fast depth: the Campaign API saves workflow versions (DAGs of steps) and
rejects bad workflows with a named, plain-language reason, never a server error."""

import json
import random
from typing import Any

import httpx
import pytest

from tests.api.helpers import DRAFT_APPROVE_PUBLISH, edge, save_workflow, step, workflow_name

FUZZ_SEED = 30
FUZZ_CASES = 150
HUGE_STEPS = 5_000


def rejections(response: httpx.Response) -> list[dict[str, str]]:
    assert response.status_code == 422, response.text
    detail: list[dict[str, str]] = response.json()["detail"]
    return detail


def test_saving_a_valid_workflow_returns_201_with_its_version_number(api: httpx.Client) -> None:
    name = workflow_name()

    saved = save_workflow(api, name, DRAFT_APPROVE_PUBLISH)

    assert saved["workflow"] == name
    assert saved["version"] == 1
    assert saved["dag"] == DRAFT_APPROVE_PUBLISH


def test_each_save_adds_the_next_version_and_reads_back(api: httpx.Client) -> None:
    name = workflow_name()
    second = {
        "steps": [*DRAFT_APPROVE_PUBLISH["steps"], step("hold", "wait", duration_seconds=60)],
        "edges": [*DRAFT_APPROVE_PUBLISH["edges"], edge("publish", "hold")],
    }

    save_workflow(api, name, DRAFT_APPROVE_PUBLISH)
    assert save_workflow(api, name, second)["version"] == 2

    first = api.get(f"/workflows/{name}/versions/1")
    assert first.status_code == 200, first.text
    assert first.json()["dag"] == DRAFT_APPROVE_PUBLISH
    assert api.get(f"/workflows/{name}/versions/2").json()["dag"] == second
    assert api.get(f"/workflows/{name}/versions/3").status_code == 404


def _bad(steps: list[dict[str, Any]], edges: list[dict[str, str]]) -> dict[str, Any]:
    return {"steps": steps, "edges": edges}


BAD_WORKFLOWS = {
    "cycle": _bad(
        [step("a", "agent"), step("b", "agent"), step("c", "agent")],
        [edge("a", "b"), edge("b", "c"), edge("c", "a")],
    ),
    "unknown_step_kind": _bad([step("a", "agent"), step("b", "teleport")], [edge("a", "b")]),
    "dangling_edge": _bad([step("a", "agent")], [edge("a", "ghost")]),
    "publish_without_approval": _bad(
        [step("draft", "agent"), step("publish", "publish")], [edge("draft", "publish")]
    ),
    "publish_without_content": _bad(
        [step("approve", "approval"), step("publish", "publish")], [edge("approve", "publish")]
    ),
    "duplicate_step_id": _bad([step("a", "agent"), step("a", "render")], []),
    "invalid_shape": {"steps": "not a list"},
}


@pytest.mark.parametrize("rule", sorted(BAD_WORKFLOWS))
def test_each_kind_of_bad_workflow_gets_its_named_rejection(api: httpx.Client, rule: str) -> None:
    response = api.post(f"/workflows/{workflow_name()}/versions", json=BAD_WORKFLOWS[rule])

    found = rejections(response)
    assert rule in [r["rule"] for r in found]
    assert all(r["message"] and "Traceback" not in r["message"] for r in found)


def test_publish_after_approval_on_one_branch_only_is_rejected(api: httpx.Client) -> None:
    dag = _bad(
        [step("draft", "agent"), step("approve", "approval"), step("publish", "publish")],
        [edge("draft", "publish")],
    )

    found = rejections(api.post(f"/workflows/{workflow_name()}/versions", json=dag))

    assert [r["rule"] for r in found] == ["publish_without_approval"]
    assert "publish" in found[0]["message"]


def test_body_that_is_not_json_is_a_named_rejection(api: httpx.Client) -> None:
    response = api.post(
        f"/workflows/{workflow_name()}/versions",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert [r["rule"] for r in rejections(response)] == ["not_json"]


def _hostile_bodies() -> list[Any]:
    rng = random.Random(FUZZ_SEED)
    kinds = ["agent", "render", "approval", "publish", "wait", "", "AGENT", None, 7]
    ids = ["a", "b", "c", "", "A B", "x" * 500, None, 3]
    fixed: list[Any] = [
        None,
        [],
        {},
        "",
        0,
        {"steps": []},
        {"steps": [], "edges": []},
        {"steps": [{}], "edges": [{}]},
        {"steps": [step(f"s{i}", "agent") for i in range(HUGE_STEPS)], "edges": []},
        {"steps": [step("a", "wait")], "edges": []},
        {"steps": [step("a", "wait", duration_seconds=-1)], "edges": []},
        {"steps": [step("a", "agent")], "edges": [edge("a", "a")]},
        {"steps": [step("a", "agent", extra=True)], "edges": []},
        {"steps": [step("a", "agent")], "edges": [], "more": 1},
    ]
    generated = []
    for _ in range(FUZZ_CASES):
        steps = [
            {"id": rng.choice(ids), "kind": rng.choice(kinds)} for _ in range(rng.randint(0, 6))
        ]
        edges = [{"from": rng.choice(ids), "to": rng.choice(ids)} for _ in range(rng.randint(0, 6))]
        generated.append({"steps": steps, "edges": edges})
    return fixed + generated


def test_hostile_bodies_get_422_with_plain_language_never_500(api: httpx.Client) -> None:
    for body in _hostile_bodies():
        response = api.post(f"/workflows/{workflow_name()}/versions", content=json.dumps(body))

        assert response.status_code in (201, 422), (body, response.text)
        if response.status_code == 422:
            found = rejections(response)
            assert found, body
            assert all(isinstance(r["rule"], str) and r["message"] for r in found), body


def test_bad_workflow_name_is_rejected(api: httpx.Client) -> None:
    response = api.post("/workflows/Not A Name!/versions", json=DRAFT_APPROVE_PUBLISH)

    assert response.status_code == 422
