"""Judge agreement: a few assets a person labeled acceptable or not, run through the same
Campaign API, and how often the judge's score lands on the same side of the floor. The
result is written to a file in git so a rubric change shows how it moved."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from evals.campaign import create_and_wait

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
    def errored(self) -> int:
        return sum("error" in r for r in self.rows)

    @property
    def rate(self) -> float:
        return round(self.agreed / self.total, 4) if self.total else 0.0


def load_labels(path: Path = LABELS_PATH) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = json.loads(path.read_text())
    return labels


def _row(api: httpx.Client, label: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One label's outcome. A failed request is recorded as an error, never as agreement."""
    base = {"id": label["id"], "step": label["step"]}
    try:
        _, body = create_and_wait(api, label["report"], timeout)
    except httpx.HTTPError as err:
        return {**base, "error": str(err)}
    score = {s["step"]: s["score"] for s in body.get("scores", [])}.get(label["step"])
    judged_ok = score is not None and score >= FLOOR
    return {
        **base,
        "human": "acceptable" if label["acceptable"] else "not acceptable",
        "score": score,
        "agrees": judged_ok == label["acceptable"],
    }


def measure(api: httpx.Client, labels: list[dict[str, Any]], timeout: float) -> Agreement:
    """Agreement over the labels that ran; labels whose request failed are counted apart."""
    rows = [_row(api, label, timeout) for label in labels]
    judged = [r for r in rows if "error" not in r]
    return Agreement(sum(r["agrees"] for r in judged), len(judged), rows)


def write(path: Path, agreement: Agreement, depth: str) -> None:
    body = {
        "depth": depth,
        "floor": FLOOR,
        "agreed": agreement.agreed,
        "total": agreement.total,
        "errored": agreement.errored,
        "rate": agreement.rate,
        "rows": agreement.rows,
    }
    path.write_text(json.dumps(body, indent=2) + "\n")


def depth() -> str:
    return "live" if os.environ.get("ACE_DEPTH") == "live" else "fast"
