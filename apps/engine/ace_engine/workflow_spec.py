"""Workflow validation: `validate(dag)` returns every named rejection, empty when valid.

Shape comes from workflow.schema.json, the one source of truth; graph rules come from
`dag`. Every message is plain language a marketer can act on."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from ace_engine import dag as graph

WORKFLOW_SCHEMA: dict[str, Any] = json.loads(
    (Path(__file__).parent / "workflow.schema.json").read_text()
)
_VALIDATOR = jsonschema.Draft202012Validator(WORKFLOW_SCHEMA)
_KINDS = ", ".join(WORKFLOW_SCHEMA["$defs"]["StepKind"]["enum"])
MAX_SHAPE_ERRORS = 10


@dataclass(frozen=True)
class Rejection:
    rule: str
    message: str


def _where(error: jsonschema.ValidationError) -> str:
    return ".".join(str(p) for p in error.absolute_path) or "workflow"


def _shape_rejection(error: jsonschema.ValidationError) -> Rejection:
    path = list(error.absolute_path)
    if path[-1:] == ["kind"] and error.validator == "enum":
        return Rejection(
            "unknown_step_kind",
            f"{_where(error)}: {error.instance!r} is not a step kind; use one of {_KINDS}",
        )
    return Rejection("invalid_shape", f"{_where(error)}: {error.message[:200]}")


def _shape(instance: object) -> list[Rejection]:
    errors = sorted(_VALIDATOR.iter_errors(instance), key=lambda e: list(map(str, e.path)))
    return [_shape_rejection(e) for e in errors[:MAX_SHAPE_ERRORS]]


def _duplicates(dag: graph.Dag) -> list[Rejection]:
    seen: set[str] = set()
    rejections = []
    for step in dag["steps"]:
        if step["id"] in seen:
            rejections.append(Rejection("duplicate_step_id", f"two steps are named {step['id']!r}"))
        seen.add(step["id"])
    return rejections


def _dangling(dag: graph.Dag) -> list[Rejection]:
    ids = {s["id"] for s in dag["steps"]}
    return [
        Rejection(
            "dangling_edge",
            f"the edge {e['from']!r} -> {e['to']!r} names a step that does not exist",
        )
        for e in dag["edges"]
        if e["from"] not in ids or e["to"] not in ids
    ]


def _publish_rules(dag: graph.Dag) -> list[Rejection]:
    kinds = {s["id"]: s["kind"] for s in dag["steps"]}
    rejections = []
    for step in dag["steps"]:
        if step["kind"] != graph.PUBLISH:
            continue
        before = {kinds[a] for a in graph.ancestors(dag, step["id"])}
        if graph.APPROVAL not in before:
            rejections.append(
                Rejection(
                    "publish_without_approval",
                    f"publish step {step['id']!r} needs an approval step before it, "
                    "so nothing goes out without a human's yes",
                )
            )
        if graph.AGENT not in before:
            rejections.append(
                Rejection(
                    "publish_without_content",
                    f"publish step {step['id']!r} needs an agent step before it "
                    "to write what it publishes",
                )
            )
    return rejections


def validate(instance: object) -> list[Rejection]:
    """Every reason `instance` is not a valid workflow DAG; empty when it is valid."""
    shape = _shape(instance)
    if shape:
        return shape
    assert isinstance(instance, dict)
    structural = _duplicates(instance) + _dangling(instance)
    if structural:
        return structural
    if graph.has_cycle(instance):
        return [
            Rejection(
                "cycle",
                "the steps loop back on themselves; a workflow must not return to an "
                "earlier step (use a review loop on a step instead)",
            )
        ]
    return _publish_rules(instance)
