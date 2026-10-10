"""Graph rules for a campaign workflow DAG. Pure and deterministic, so the Temporal
workflow can use it. The DAG's shape is checked against workflow.schema.json first."""

from typing import Any

Dag = dict[str, Any]
Step = dict[str, Any]

AGENT = "agent"
RENDER = "render"
APPROVAL = "approval"
PUBLISH = "publish"
WAIT = "wait"


def default_dag() -> Dag:
    """The workflow a campaign runs when it names none: draft, wait for a human, publish.
    A fresh dict each call, so no caller can change another's copy."""
    return {
        "steps": [
            {"id": "email_draft", "kind": AGENT},
            {"id": "approval", "kind": APPROVAL},
            {"id": "publish", "kind": PUBLISH},
        ],
        "edges": [
            {"from": "email_draft", "to": "approval"},
            {"from": "approval", "to": "publish"},
        ],
    }


def _parents(dag: Dag) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {s["id"]: [] for s in dag["steps"]}
    for edge in dag["edges"]:
        parents[edge["to"]].append(edge["from"])
    return parents


def ordered(dag: Dag) -> list[Step]:
    """The steps in an order that respects every edge; ties keep the declared order.
    Steps on a cycle are left out."""
    parents = _parents(dag)
    done: set[str] = set()
    result: list[Step] = []
    while True:
        wave = ready_steps(dag, done, parents)
        if not wave:
            return result
        first = wave[0]
        result.append(first)
        done.add(first["id"])


def ready_steps(
    dag: Dag, done: set[str], parents: dict[str, list[str]] | None = None
) -> list[Step]:
    """The steps not yet done whose parents are all done, in declared order."""
    parents = parents if parents is not None else _parents(dag)
    return [
        s for s in dag["steps"] if s["id"] not in done and all(p in done for p in parents[s["id"]])
    ]


def has_cycle(dag: Dag) -> bool:
    return len(ordered(dag)) < len(dag["steps"])


def ancestors(dag: Dag, step_id: str) -> set[str]:
    """Every step that must succeed before `step_id` can start."""
    parents = _parents(dag)
    seen: set[str] = set()
    pending = list(parents[step_id])
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(parents[current])
    return seen


def latest_ancestor_of_kind(dag: Dag, step_id: str, kind: str) -> str | None:
    """The last step of `kind` before `step_id`, in run order; None when there is none."""
    before = ancestors(dag, step_id)
    matches = [s["id"] for s in ordered(dag) if s["id"] in before and s["kind"] == kind]
    return matches[-1] if matches else None
