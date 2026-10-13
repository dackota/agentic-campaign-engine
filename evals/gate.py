"""The CI gate: each golden report's scores are compared to a baseline file in git, and a
drop past the margin fails. The baseline changes only through `--update-baseline`
(docs/decisions/eval-gate.md)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from evals.campaign import AWAITING

if TYPE_CHECKING:
    from evals.runner import ReportResult

BASELINE_PATH = Path(__file__).with_name("baseline.json")
DEFAULT_MARGIN = 0.05
MAX_JUDGE_SCORE = 5
PLACES = 2

Scores = dict[str, float | None]


@dataclass(frozen=True)
class Baseline:
    margin: float
    reports: dict[str, Scores]


@dataclass(frozen=True)
class Verdict:
    margin: float
    lines: list[str]
    regressed: int

    @property
    def passed(self) -> bool:
        return self.regressed == 0


def quality(result: "ReportResult") -> float:
    """The share of this report's yes-or-no outcomes that went well: the campaign reached
    approval, every key fact is carried, and every hard check passed."""
    everything = result.assets + ([result.research] if result.research else [])
    outcomes = [
        result.status == AWAITING and not result.error,
        *result.key_facts.values(),
        *(c.passed for a in everything for c in a.checks),
    ]
    return sum(outcomes) / len(outcomes)


def judge_mean(result: "ReportResult") -> float | None:
    """The judge's mean score over the assets, as a share of the top score."""
    scores = list(result.judge_scores.values())
    return sum(scores) / len(scores) / MAX_JUDGE_SCORE if scores else None


def scores_of(result: "ReportResult") -> Scores:
    return {"quality": round(quality(result), 4), "judge": _round(judge_mean(result))}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or "margin" not in raw or "reports" not in raw:
        raise ValueError(f"{path.name} must be an object with margin and reports")
    return Baseline(float(raw["margin"]), dict(raw["reports"]))


def write_baseline(path: Path, results: "list[ReportResult]", margin: float | None = None) -> None:
    """Replace the baseline with these results. Only the explicit update command calls this."""
    if margin is None:
        margin = load_baseline(path).margin if path.exists() else DEFAULT_MARGIN
    body = {"margin": margin, "reports": {r.id: scores_of(r) for r in results}}
    path.write_text(json.dumps(body, indent=2) + "\n")


def _fmt(value: float | None) -> str:
    return "none" if value is None else f"{value:.{PLACES}f}"


def _judge_drop(base: Scores, now: Scores) -> float:
    before, after = base.get("judge"), now.get("judge")
    return 0.0 if before is None or after is None else before - after


def _compare_one(baseline: Baseline, result: "ReportResult") -> tuple[str, bool]:
    base = baseline.reports.get(result.id)
    now = scores_of(result)
    if base is None:
        return f"FAIL {result.id}: not in the baseline; add it with --update-baseline", False
    drops = {
        "quality": (base["quality"] or 0.0) - (now["quality"] or 0.0),
        "judge": _judge_drop(base, now),
    }
    worse = [name for name, drop in drops.items() if drop > baseline.margin + 1e-9]
    detail = ", ".join(f"{n} {_fmt(now[n])}, baseline {_fmt(base.get(n))}" for n in drops)
    if not worse:
        return f"PASS {result.id}: {detail}", True
    return f"FAIL {result.id}: {detail} ({' and '.join(worse)} dropped past margin)", False


def compare(baseline: Baseline, results: "list[ReportResult]") -> Verdict:
    """Every report against its baseline entry; a drop past the margin fails."""
    rows = [_compare_one(baseline, r) for r in results]
    return Verdict(baseline.margin, [line for line, _ in rows], sum(not ok for _, ok in rows))


def render_verdict(verdict: Verdict) -> str:
    head = f"gate: margin {_fmt(verdict.margin)}"
    tail = (
        f"gate: {verdict.regressed} report(s) regressed past the baseline"
        if verdict.regressed
        else "gate: no report regressed past the baseline"
    )
    return "\n".join([head, *verdict.lines, tail]) + "\n"
