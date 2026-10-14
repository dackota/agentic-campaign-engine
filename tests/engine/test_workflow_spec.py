"""The workflow validator rejects every bad workflow with a named, plain-language reason and
never raises, whatever it is handed."""

import random
from typing import Any

import pytest
from ace_engine.workflow_spec import Rejection, validate

from tests.support.dag import DRAFT_APPROVE_PUBLISH, edge, step

FUZZ_SEED = 30
FUZZ_CASES = 150
HUGE_STEPS = 5_000
# A body with a thousand mistakes is told of at most this many, so the answer stays readable.
SHAPE_ERROR_CAP = 10


def _bad(steps: list[dict[str, Any]], edges: list[dict[str, str]]) -> dict[str, Any]:
    return {"steps": steps, "edges": edges}


NO_APPROVAL = _bad([step("writer", "agent"), step("ship", "publish")], [edge("writer", "ship")])
BAD_WORKFLOWS = {
    "cycle": _bad(
        [step("a", "agent"), step("b", "agent"), step("c", "agent")],
        [edge("a", "b"), edge("b", "c"), edge("c", "a")],
    ),
    "unknown_step_kind": _bad([step("a", "agent"), step("b", "teleport")], [edge("a", "b")]),
    "dangling_edge": _bad([step("a", "agent")], [edge("a", "ghost")]),
    "publish_without_approval": NO_APPROVAL,
    "publish_without_content": _bad(
        [step("approve", "approval"), step("publish", "publish")], [edge("approve", "publish")]
    ),
    "duplicate_step_id": _bad([step("a", "agent"), step("a", "render")], []),
    "invalid_shape": {"steps": "not a list"},
}


@pytest.mark.parametrize("rule", sorted(BAD_WORKFLOWS))
def test_each_kind_of_bad_workflow_gets_its_named_rejection(rule: str) -> None:
    found = validate(BAD_WORKFLOWS[rule])

    assert rule in [r.rule for r in found]
    assert all(r.message and "Traceback" not in r.message for r in found)


def test_publish_after_approval_on_one_branch_only_is_rejected() -> None:
    dag = _bad(
        [step("draft", "agent"), step("approve", "approval"), step("publish", "publish")],
        [edge("draft", "publish")],
    )

    found = validate(dag)

    assert [r.rule for r in found] == ["publish_without_approval"]
    assert "publish" in found[0].message


def test_a_publish_without_an_approval_says_what_to_add() -> None:
    [found] = validate(NO_APPROVAL)

    assert found == Rejection(
        "publish_without_approval",
        "publish step 'ship' needs an approval step before it, "
        "so nothing goes out without a human's yes",
    )


def test_a_valid_workflow_has_no_rejections() -> None:
    assert validate(DRAFT_APPROVE_PUBLISH) == []


def test_a_step_keeps_its_retry_and_review_settings() -> None:
    dag = _bad(
        [
            step("writer", "agent", max_attempts=5, review_rounds=2),
            step("ok", "approval"),
            step("ship", "publish"),
        ],
        [edge("writer", "ok"), edge("ok", "ship")],
    )

    assert validate(dag) == []


def test_an_out_of_range_policy_is_rejected_in_plain_words() -> None:
    dag = _bad(
        [step("writer", "agent", max_attempts=0), step("ok", "approval"), step("ship", "publish")],
        [edge("writer", "ok"), edge("ok", "ship")],
    )

    [found, *_] = validate(dag)

    assert found.rule == "invalid_shape"
    assert "max_attempts" in found.message


def test_retry_policy_and_timeout_are_accepted_and_bounded() -> None:
    tuned = step(
        "draft",
        "agent",
        timeout_seconds=90,
        retry={"maximum_attempts": 4, "initial_interval_seconds": 0.5},
    )

    assert validate(_bad([tuned], [])) == []
    for bad in (
        {"timeout_seconds": 0},
        {"timeout_seconds": 86_401},
        {"retry": {"maximum_attempts": 0}},
        {"retry": {"maximum_attempts": 11}},
        {"retry": {"initial_interval_seconds": 0}},
        {"retry": {"maximum_attempts": 2, "forever": True}},
    ):
        found = validate(_bad([step("draft", "agent", **bad)], []))
        assert [r.rule for r in found] == ["invalid_shape"], bad


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
        {"steps": [{} for _ in range(HUGE_STEPS)], "edges": []},
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


def test_hostile_workflows_get_named_plain_rejections_and_never_an_error() -> None:
    for body in _hostile_bodies():
        found = validate(body)

        assert sum(r.rule == "invalid_shape" for r in found) <= SHAPE_ERROR_CAP, body
        assert all(isinstance(r.rule, str) and r.message for r in found), body
