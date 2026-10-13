"""The judge. One agent step scores every asset of a run against a written rubric
(judge_rubric.md), a whole number from MIN_SCORE to MAX_SCORE with a reason. An asset scored
below FLOOR stops the run; a score at or above it never does
(docs/decisions/judge-scores.md)."""

from pathlib import Path
from typing import Any

from ace_engine.contracts import violations

RUBRIC_PATH = Path(__file__).parent / "judge_rubric.md"
MIN_SCORE = 1
MAX_SCORE = 5
FLOOR = 3
JUDGE_STEP = "judge"

SCORES_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["scores"],
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "score", "reason"],
                "properties": {
                    "step": {"type": "string"},
                    "score": {"type": "integer", "minimum": MIN_SCORE, "maximum": MAX_SCORE},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}

RUBRIC = " ".join(line.strip() for line in RUBRIC_PATH.read_text().splitlines() if line.strip())
PROMPT = (
    f"You are the judge. Score every asset (each OUTPUT OF step except the strategist and "
    f"research) from {MIN_SCORE} (poor) to {MAX_SCORE} (excellent) against this rubric: "
    f"{RUBRIC} A score below {FLOOR} stops the campaign, so give one only to an asset a "
    "marketer should not see. Reply with only JSON that has the key scores: a list of objects "
    "with the keys step, score (a whole number), reason (one sentence)."
)


def score_problems(output: object) -> list[str]:
    return violations(output, SCORES_SCHEMA)


def asset_scores(output: dict[str, Any], assets: list[str]) -> list[dict[str, Any]]:
    """The judge's scores for the run's assets, in the judge's order; any other step it
    scored is ignored."""
    return [s for s in output["scores"] if s["step"] in assets]


def blocking(output: dict[str, Any], assets: list[str]) -> list[str]:
    """One sentence per asset scored below the floor, with the judge's reason."""
    return [
        f"the judge scored {s['step']} {s['score']} of {MAX_SCORE}, below the floor of "
        f"{FLOOR}: {s['reason']}"
        for s in asset_scores(output, assets)
        if s["score"] < FLOOR
    ]
