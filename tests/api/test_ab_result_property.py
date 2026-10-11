"""The A/B stats check as a property: it never calls a winner on a small sample, and the
better variant wins when the gap is large. Generated counts, fixed seed."""

import random

from campaign_api.ab_result import MIN_TOTAL_OPENS, decide

SEED = 48
CASES = 500
LARGE_MAX = 5_000


def opens(a: int, b: int) -> dict[str, dict[str, int]]:
    return {"A": {"opens": a, "clicks": 0}, "B": {"opens": b, "clicks": 0}}


def test_no_winner_when_sample_too_small() -> None:
    rng = random.Random(SEED)
    for _ in range(CASES):
        total = rng.randint(0, MIN_TOTAL_OPENS - 1)
        a = rng.randint(0, total)
        b = total - a
        for shown in (opens(a, b), opens(b, a)):
            result = decide(shown)
            assert result.winner is None
            assert result.confidence is None


def test_no_winner_when_a_variant_is_missing() -> None:
    assert decide({}).winner is None
    assert decide({"A": {"opens": 500, "clicks": 400}}).winner is None


def test_better_variant_wins_when_gap_is_large() -> None:
    rng = random.Random(SEED)
    for _ in range(CASES):
        low = rng.randint(MIN_TOTAL_OPENS, LARGE_MAX)
        high = low * rng.randint(3, 10)
        better = rng.choice(["A", "B"])
        result = decide(opens(high, low) if better == "A" else opens(low, high))
        assert result.winner == better
        assert result.confidence is not None and result.confidence >= 0.95


def test_no_winner_when_open_counts_are_equal() -> None:
    assert decide(opens(200, 200)).winner is None
