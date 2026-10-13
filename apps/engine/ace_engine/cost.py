"""Cost ledger: what a model call used, what it cost, and whether a campaign's budget is
spent.

Usage comes off each A2A task reply (`metadata.usage`), per the decision in
docs/decisions/token-usage-per-campaign.md. Money is whole micro-dollars, so a campaign's
total is the exact sum of its steps."""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MICROS_PER_DOLLAR = 1_000_000
# The error type an agent step stops with when the campaign's budget is spent.
BUDGET_SPENT = "BudgetSpent"
# The model name a reply that reports no usage is booked under, at zero tokens.
UNREPORTED_MODEL = "unreported"
# The ledger's model column is this wide; a longer reported name is cut to fit.
MAX_MODEL_CHARS = 100
# No model call uses more tokens than this; a reply that says so is malformed, and the
# cap keeps a hostile number from overflowing the ledger.
MAX_TOKENS_PER_REPLY = 10_000_000


@dataclass(frozen=True)
class Price:
    """Micro-dollars per token, which is the same number as dollars per million tokens."""

    input_micros_per_token: int
    output_micros_per_token: int


# The model price table. A model it does not name costs the default: the list price of a
# pay-as-you-go frontier model ($3 in, $15 out per million tokens), so a budget errs on
# the side of pausing early. OpenCode Go is a flat monthly rate, so its calls are booked
# at this price too: the budget caps use, not the bill.
DEFAULT_PRICE = Price(input_micros_per_token=3, output_micros_per_token=15)
PRICES: dict[str, Price] = {}


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_micros(self) -> int:
        price = PRICES.get(self.model, DEFAULT_PRICE)
        return (
            self.input_tokens * price.input_micros_per_token
            + self.output_tokens * price.output_micros_per_token
        )

    def __add__(self, other: "Usage") -> "Usage":
        model = other.model if self.model == UNREPORTED_MODEL else self.model
        return Usage(
            model=model,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


NO_USAGE = Usage(model=UNREPORTED_MODEL, input_tokens=0, output_tokens=0)
# OpenAI-style names are read too, since kagent passes the gateway's numbers through, and
# the Google ADK names kagent's Python harness reports.
_INPUT_KEYS = ("input_tokens", "prompt_tokens", "promptTokenCount")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "candidatesTokenCount")
_TOTAL_KEYS = ("total_tokens", "totalTokens", "totalTokenCount")


def _count(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_TOKENS_PER_REPLY
        ):
            return value
    return None


def usage_from(raw: object) -> Usage:
    """The usage an agent reported, or no usage when it reported none a ledger can trust.
    The reply is outside input, so anything malformed counts as unreported."""
    if not isinstance(raw, dict):
        logger.warning("agent reply carried no token usage; booked at zero")
        return NO_USAGE
    input_tokens, output_tokens = _count(raw, _INPUT_KEYS), _count(raw, _OUTPUT_KEYS)
    total = _count(raw, _TOTAL_KEYS)
    if (input_tokens is None or output_tokens is None) and total is not None:
        # A total with no split: whatever input is known, the rest as output, the dearer
        # side, so a budget never undercounts.
        input_tokens = min(input_tokens or 0, total)
        output_tokens = total - input_tokens
    if input_tokens is None or output_tokens is None:
        logger.warning("agent reply carried malformed token usage; booked at zero")
        return NO_USAGE
    model = raw.get("model")
    return Usage(
        model=model[:MAX_MODEL_CHARS] if isinstance(model, str) and model else UNREPORTED_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def to_micros(dollars: float) -> int:
    return round(dollars * MICROS_PER_DOLLAR)


def to_dollars(micros: int) -> float:
    return micros / MICROS_PER_DOLLAR


def is_budget_spent(budget_micros: int | None, spent_micros: int) -> bool:
    """True when the campaign has a budget and has spent all of it."""
    return budget_micros is not None and spent_micros >= budget_micros
