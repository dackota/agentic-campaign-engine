"""The fake Marketo's simulated audience: seeded personas with a hidden scoring rule.
Same seed, same variants, same events. Engagement is spread over days of simulated time."""

import random

from fake_marketo.audience import AUDIENCE_SIZE, SECONDS_PER_DAY, personas, simulate

PROPERTY_SEED = 47
PROPERTY_CASES = 60
URGENT = {
    "label": "A",
    "subject": "Urgent: patch your VPN today",
    "preheader": "Act now",
    "body": "Patch now.",
    "callToAction": "Patch",
}
DULL = {
    "label": "B",
    "subject": "A long and rather meandering note about edge router firmware lifecycles",
    "preheader": "Read more inside",
    "body": "x" * 600,
    "callToAction": "Click here to read the full advisory in your browser",
}


def test_same_seed_always_gives_the_same_events() -> None:
    rng = random.Random(PROPERTY_SEED)
    for _ in range(PROPERTY_CASES):
        seed = rng.randint(-(2**63), 2**63)
        size = rng.randint(0, 80)

        first = simulate(seed, [URGENT, DULL], size)
        second = simulate(seed, [URGENT, DULL], size)

        assert first == second
        assert first == sorted(first, key=lambda e: (e.at_seconds, e.persona, e.type))
        assert all(e.type in {"open", "click"} for e in first)
        assert all(e.at_seconds >= 0 for e in first)
        opened = {(e.persona, e.variant) for e in first if e.type == "open"}
        assert all((e.persona, e.variant) in opened for e in first if e.type == "click")


def test_personas_are_seeded_and_differ_by_seed() -> None:
    assert len(personas(1, AUDIENCE_SIZE)) == AUDIENCE_SIZE
    assert personas(1, AUDIENCE_SIZE) == personas(1, AUDIENCE_SIZE)
    assert personas(1, AUDIENCE_SIZE) != personas(2, AUDIENCE_SIZE)


def test_different_seeds_give_different_events() -> None:
    assert simulate(1, [URGENT, DULL]) != simulate(2, [URGENT, DULL])


def test_better_scoring_variant_draws_more_engagement() -> None:
    urgent_total = dull_total = 0
    for seed in range(20):
        events = simulate(seed, [URGENT, DULL], 200)
        urgent_total += sum(1 for e in events if e.variant == "A")
        dull_total += sum(1 for e in events if e.variant == "B")

    assert urgent_total > dull_total * 1.2


def test_events_span_days_of_simulated_time() -> None:
    events = simulate(7, [URGENT, DULL], 200)

    assert max(e.at_seconds for e in events) > SECONDS_PER_DAY
