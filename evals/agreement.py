"""Judge agreement: a few assets a person labeled acceptable or not, run through the same
Campaign API, and how often the judge's score lands on the same side of the floor. The
result is written to a file in git so a rubric change shows how it moved."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

LABELS_PATH = Path(__file__).with_name("judge_labels.json")
AGREEMENT_PATH = Path(__file__).with_name("judge_agreement.json")
# Keep equal to ace_engine.judge.FLOOR (a test checks).
FLOOR = 3


@dataclass(frozen=True)
class Agreement:
    agreed: int
    total: int
    rows: list[dict[str, Any]]

    @property
    def rate(self) -> float:
        return round(self.agreed / self.total, 4) if self.total else 0.0


def load_labels(path: Path = LABELS_PATH) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = json.loads(path.read_text())
    return labels


def _row(api: httpx.Client, label: dict[str, Any], timeout: float) -> dict[str, Any]:
    from evals.runner import WORKFLOW, wait_for

    try:
        created = api.post(
            "/campaigns",
            json={"report": label["report"], "workflow": WORKFLOW, "use_step_cache": True},
        )
        created.raise_for_status()
        body = wait_for(api, created.json()["id"], timeout)
    except httpx.HTTPError:
        body = {}
    scores = {s["step"]: s["score"] for s in body.get("scores", [])}
    score = scores.get(label["step"])
    judged_ok = score is not None and score >= FLOOR
    return {
        "id": label["id"],
        "step": label["step"],
        "human": "acceptable" if label["acceptable"] else "not acceptable",
        "score": score,
        "agrees": judged_ok == label["acceptable"],
    }


def measure(api: httpx.Client, labels: list[dict[str, Any]], timeout: float) -> Agreement:
    rows = [_row(api, label, timeout) for label in labels]
    return Agreement(sum(r["agrees"] for r in rows), len(rows), rows)


def write(path: Path, agreement: Agreement, depth: str) -> None:
    body = {
        "depth": depth,
        "floor": FLOOR,
        "agreed": agreement.agreed,
        "total": agreement.total,
        "rate": agreement.rate,
        "rows": agreement.rows,
    }
    path.write_text(json.dumps(body, indent=2) + "\n")


def depth() -> str:
    return "live" if os.environ.get("ACE_DEPTH") == "live" else "fast"
