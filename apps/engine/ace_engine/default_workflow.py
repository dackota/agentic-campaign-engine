"""The workflow every deployment seeds: "Threat report to campaign". A strategist and a
research agent run first, then the design agent and four writers at the same time, then the judge
scores their assets, then a human approves and the email goes out."""

from typing import Any

DEFAULT_WORKFLOW_NAME = "threat-report-to-campaign"
DEFAULT_WORKFLOW_VERSION = 1

# Every writer's draft goes to the brand reviewer before a human sees it.
REVIEW_ROUNDS = 2
_WRITERS = ("landing_page", "social", "one_pager", "email_writer")


def default_workflow_dag() -> dict[str, Any]:
    """A fresh dict each call. The email writer is declared last among the writers: the
    publish step sends the output of the last agent step before it, in declared order."""
    return {
        "steps": [
            {"id": "strategist", "kind": "agent"},
            {"id": "research", "kind": "agent"},
            # Declared before the writers: the publish step sends the last agent step's output.
            {"id": "design", "kind": "agent"},
            *({"id": w, "kind": "agent", "review_rounds": REVIEW_ROUNDS} for w in _WRITERS),
            # Scores every asset before a human sees one; a score below the floor stops the run.
            {"id": "judge", "kind": "agent"},
            {"id": "approval", "kind": "approval"},
            {"id": "publish", "kind": "publish"},
        ],
        "edges": [
            {"from": "strategist", "to": "research"},
            {"from": "research", "to": "design"},
            *({"from": "research", "to": w} for w in _WRITERS),
            {"from": "design", "to": "judge"},
            *({"from": w, "to": "judge"} for w in _WRITERS),
            {"from": "judge", "to": "approval"},
            {"from": "approval", "to": "publish"},
        ],
    }
