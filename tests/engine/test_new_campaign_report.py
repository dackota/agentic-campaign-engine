"""A new campaign needs a report: not empty, not blank, not past the limit."""

import random

import pytest
from campaign_api.main import MAX_REPORT_CHARS, NewCampaign
from pydantic import ValidationError

SEED = 7
CASES = 200
WHITESPACE = " \t\n\r\x0b\x0c  "


def test_a_report_of_nothing_but_whitespace_is_refused() -> None:
    rng = random.Random(SEED)
    blanks = [
        "",
        " ",
        "   \n",
        *("".join(rng.choices(WHITESPACE, k=rng.randint(1, 50))) for _ in range(CASES)),
    ]

    for report in blanks:
        with pytest.raises(ValidationError):
            NewCampaign(report=report)


def test_a_report_at_the_limit_is_taken_and_one_character_more_is_not() -> None:
    assert len(NewCampaign(report="x" * MAX_REPORT_CHARS).report) == MAX_REPORT_CHARS
    with pytest.raises(ValidationError):
        NewCampaign(report="x" * (MAX_REPORT_CHARS + 1))


def test_a_report_with_text_among_whitespace_is_kept_as_written() -> None:
    assert NewCampaign(report="  Volt Typhoon\n").report == "  Volt Typhoon\n"
