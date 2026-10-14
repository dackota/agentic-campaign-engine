"""The cost ledger: what a reply's usage is booked as, what it costs, and when a budget is
spent. The default price is $3 per million input tokens and $15 per million output tokens,
so 3 and 15 micro-dollars a token."""

import random
from typing import Any

import pytest
from ace_engine import cost
from ace_engine.cost import MAX_MODEL_CHARS, MAX_TOKENS_PER_REPLY, NO_USAGE, Usage

SCRIPTED_MODEL = "scripted-model"
SEED = 11
CASES = 500


def test_two_replies_of_a_step_add_to_its_tokens_and_cost() -> None:
    reply = cost.usage_from({"input_tokens": 1200, "output_tokens": 300, "model": SCRIPTED_MODEL})

    step = reply + reply

    assert (step.input_tokens, step.output_tokens, step.total_tokens) == (2400, 600, 3000)
    # 2400 * 3 + 600 * 15 micro-dollars.
    assert step.cost_micros == 16_200
    assert step.model == SCRIPTED_MODEL


def test_a_reply_with_no_usage_adds_nothing_and_leaves_the_model_to_the_next_one() -> None:
    reply = cost.usage_from({"input_tokens": 10, "output_tokens": 5, "model": SCRIPTED_MODEL})

    assert (NO_USAGE + reply).model == SCRIPTED_MODEL
    assert (reply + NO_USAGE) == reply


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A total with no split is booked as output, the dearer side, so a budget never
        # undercounts: 700 * 15 = 10_500 micro-dollars.
        ({"total_tokens": 700}, (0, 700, 10_500)),
        ({"totalTokens": 700}, (0, 700, 10_500)),
        ({"totalTokenCount": 700}, (0, 700, 10_500)),
        ({"total_tokens": 700, "input_tokens": 200}, (200, 500, 8_100)),
        # More input than the total says: input is cut to the total.
        ({"total_tokens": 100, "input_tokens": 400}, (100, 0, 300)),
        ({"prompt_tokens": 1000, "completion_tokens": 500}, (1000, 500, 10_500)),
        ({"promptTokenCount": 1000, "candidatesTokenCount": 500}, (1000, 500, 10_500)),
        ({"input_tokens": 0, "output_tokens": 0}, (0, 0, 0)),
        (
            {"input_tokens": MAX_TOKENS_PER_REPLY, "output_tokens": 0},
            (MAX_TOKENS_PER_REPLY, 0, 30_000_000),
        ),
    ],
)
def test_usage_is_read_from_the_names_the_agents_report_it_under(
    raw: dict[str, Any], expected: tuple[int, int, int]
) -> None:
    booked = cost.usage_from(raw)

    assert (booked.input_tokens, booked.output_tokens, booked.cost_micros) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "1200",
        [1200, 300],
        {},
        {"input_tokens": 1200},
        {"input_tokens": True, "output_tokens": True},
        {"input_tokens": -1, "output_tokens": 5},
        {"input_tokens": 1.5, "output_tokens": 5},
        {"input_tokens": "12", "output_tokens": 5},
        {"input_tokens": MAX_TOKENS_PER_REPLY + 1, "output_tokens": 5},
        {"total_tokens": MAX_TOKENS_PER_REPLY + 1},
    ],
)
def test_usage_a_ledger_cannot_trust_is_booked_at_zero(raw: object) -> None:
    assert cost.usage_from(raw) == NO_USAGE


@pytest.mark.parametrize(
    ("model", "booked_as"),
    [
        ("m" * (MAX_MODEL_CHARS + 50), "m" * MAX_MODEL_CHARS),
        ("", cost.UNREPORTED_MODEL),
        (None, cost.UNREPORTED_MODEL),
        (7, cost.UNREPORTED_MODEL),
    ],
)
def test_a_model_name_is_cut_to_the_ledger_column_or_booked_as_unreported(
    model: object, booked_as: str
) -> None:
    raw = {"input_tokens": 1, "output_tokens": 1, "model": model}

    assert cost.usage_from(raw).model == booked_as


def _hostile_value(rng: random.Random) -> object:
    return rng.choice(
        [None, True, False, 0, -1, 7, 1e308, float("nan"), "x", "", [], {}, [1], 10**30,
         MAX_TOKENS_PER_REPLY, MAX_TOKENS_PER_REPLY + 1]
    )  # fmt: skip


def test_whatever_an_agent_reports_the_ledger_books_whole_bounded_tokens() -> None:
    rng = random.Random(SEED)
    keys = [
        "input_tokens", "output_tokens", "total_tokens", "prompt_tokens",
        "completion_tokens", "totalTokens", "model",
    ]  # fmt: skip

    for _ in range(CASES):
        raw = {k: _hostile_value(rng) for k in rng.sample(keys, rng.randint(0, len(keys)))}

        booked = cost.usage_from(raw)

        assert isinstance(booked, Usage)
        assert 0 <= booked.input_tokens <= MAX_TOKENS_PER_REPLY, raw
        assert 0 <= booked.output_tokens <= MAX_TOKENS_PER_REPLY, raw
        assert 0 < len(booked.model) <= MAX_MODEL_CHARS
        assert booked.cost_micros >= 0


@pytest.mark.parametrize(
    ("budget", "spent", "is_spent"),
    [
        (None, 10**12, False),
        (10_000, 0, False),
        (10_000, 9_999, False),
        (10_000, 10_000, True),
        (10_000, 21_000, True),
    ],
)
def test_a_budget_is_spent_once_the_spend_reaches_it(
    budget: int | None, spent: int, is_spent: bool
) -> None:
    assert cost.is_budget_spent(budget, spent) is is_spent


def test_money_is_whole_micro_dollars_both_ways() -> None:
    assert cost.to_micros(0.0162) == 16_200
    assert cost.to_micros(0.01) == 10_000
    assert cost.to_dollars(16_200) == pytest.approx(0.0162)
