"""The workflow every deployment seeds: "Threat report to campaign". A strategist and a
research agent run first, then four writers at the same time, then a human approves and
the email goes out."""

from typing import Any

DEFAULT_WORKFLOW_NAME = "threat-report-to-campaign"
DEFAULT_WORKFLOW_VERSION = 1

_WRITERS = ("landing_page", "social", "one_pager", "email_writer")


def default_workflow_dag() -> dict[str, Any]:
    """A fresh dict each call. The email writer is declared last among the writers: the
    publish step sends the output of the last agent step before it, in declared order."""
    return {
        "steps": [
            {"id": "strategist", "kind": "agent"},
            {"id": "research", "kind": "agent"},
            *({"id": w, "kind": "agent"} for w in _WRITERS),
            {"id": "approval", "kind": "approval"},
            {"id": "publish", "kind": "publish"},
        ],
        "edges": [
            {"from": "strategist", "to": "research"},
            *({"from": "research", "to": w} for w in _WRITERS),
            *({"from": w, "to": "approval"} for w in _WRITERS),
            {"from": "approval", "to": "publish"},
        ],
    }
