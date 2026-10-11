"""The fake Marketo's simulated audience: seeded personas who open and click the variants
of a send. Which variant draws more is decided by a hidden scoring rule that no caller
sees; a persona's own taste tilts it. The same seed always gives the same events.

Times are simulated seconds after the send. The delivery loop divides them by a time
speed, so days of engagement arrive in seconds.
"""

import random
from dataclasses import dataclass
from typing import Any

AUDIENCE_SIZE = 120
SECONDS_PER_DAY = 86_400
MAX_ENGAGEMENT_DAYS = 5
MEAN_OPEN_DELAY_SECONDS = SECONDS_PER_DAY
MEAN_CLICK_DELAY_SECONDS = SECONDS_PER_DAY // 8
# The hidden rule: a variant is scored on how short its subject and call to action are
# and on whether it sounds urgent. These are the numbers a user must not be told.
SUBJECT_LIMIT_CHARS = 80
CTA_LIMIT_CHARS = 50
URGENT_WORDS = ("urgent", "now", "today", "immediately", "alert", "critical")
BASE_OPEN_RATE = 0.1
OPEN_RATE_GAIN = 0.75
BASE_CLICK_RATE = 0.1
CLICK_RATE_GAIN = 0.5


@dataclass(frozen=True)
class Persona:
    name: str
    brevity_taste: float
    urgency_taste: float
    cta_taste: float


@dataclass(frozen=True)
class Engagement:
    at_seconds: int
    persona: str
    type: str  # "open" or "click"
    variant: str


def personas(seed: int, size: int = AUDIENCE_SIZE) -> list[Persona]:
    """`size` personas drawn from `seed`; each weighs the three scoring cues differently."""
    rng = random.Random(f"personas:{seed}")
    audience = []
    for index in range(size):
        weights = [rng.uniform(0.2, 1.0) for _ in range(3)]
        total = sum(weights)
        audience.append(Persona(f"persona-{index:03d}", *(w / total for w in weights)))
    return audience


def _cues(variant: dict[str, Any]) -> tuple[float, float, float]:
    subject = str(variant["subject"])
    brevity = max(0.0, 1 - len(subject) / SUBJECT_LIMIT_CHARS)
    is_urgent = any(word in subject.lower() for word in URGENT_WORDS)
    cta = max(0.0, 1 - len(str(variant["callToAction"])) / CTA_LIMIT_CHARS)
    return brevity, 1.0 if is_urgent else 0.0, cta


def score(persona: Persona, variant: dict[str, Any]) -> float:
    """How much this persona likes this variant, 0 to 1. Hidden from everything outside."""
    brevity, urgency, cta = _cues(variant)
    return (
        persona.brevity_taste * brevity + persona.urgency_taste * urgency + persona.cta_taste * cta
    )


def _delay(rng: random.Random, mean_seconds: int) -> int:
    return min(int(rng.expovariate(1 / mean_seconds)), MAX_ENGAGEMENT_DAYS * SECONDS_PER_DAY)


def simulate(
    seed: int, variants: list[dict[str, Any]], size: int = AUDIENCE_SIZE
) -> list[Engagement]:
    """The opens and clicks the audience makes, in order. Personas split across the
    variants in turn; a click always follows its persona's open."""
    events: list[Engagement] = []
    for index, persona in enumerate(personas(seed, size)):
        variant = variants[index % len(variants)]
        liking = score(persona, variant)
        rng = random.Random(f"engage:{seed}:{persona.name}")
        label = str(variant["label"])
        if rng.random() >= BASE_OPEN_RATE + OPEN_RATE_GAIN * liking:
            continue
        opened_at = _delay(rng, MEAN_OPEN_DELAY_SECONDS)
        events.append(Engagement(opened_at, persona.name, "open", label))
        if rng.random() < BASE_CLICK_RATE + CLICK_RATE_GAIN * liking:
            clicked_at = opened_at + _delay(rng, MEAN_CLICK_DELAY_SECONDS)
            events.append(Engagement(clicked_at, persona.name, "click", label))
    return sorted(events, key=lambda e: (e.at_seconds, e.persona, e.type))
