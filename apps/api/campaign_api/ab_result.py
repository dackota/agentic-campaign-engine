"""The A/B result: a winner with its confidence, or no decision yet. Method and limits
are in docs/decisions/ab-result-stats-check.md."""

import math
from dataclasses import dataclass

MIN_TOTAL_OPENS = 30  # both variants together; below this the sample is too small to call
MIN_CONFIDENCE = 0.95
VARIANTS = ("A", "B")


@dataclass(frozen=True)
class AbResult:
    winner: str | None
    confidence: float | None


NO_DECISION = AbResult(winner=None, confidence=None)


def decide(engagement: dict[str, dict[str, int]]) -> AbResult:
    """Open rate of A against B, both sent to equally many readers. The test is the
    small-rate form of the two-proportion z-test, z = (a - b) / sqrt(a + b): it needs no
    send count, and it understates confidence (errs toward no decision) when the open
    rate is high (see the ADR).
    Confidence is 1 - p, two-sided."""
    if not all(v in engagement for v in VARIANTS):
        return NO_DECISION
    a, b = (engagement[v]["opens"] for v in VARIANTS)
    if a + b < MIN_TOTAL_OPENS:
        return NO_DECISION
    confidence = math.erf(abs(a - b) / math.sqrt(a + b) / math.sqrt(2))
    if confidence < MIN_CONFIDENCE:
        return NO_DECISION
    return AbResult(winner="A" if a > b else "B", confidence=confidence)
