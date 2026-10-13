"""The hard checks: deterministic content checks run on every asset."""

from typing import Any

import pytest
from ace_engine import limits

from evals import checks
from evals.checks import CHECK_NAMES, check_asset

REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances."
CLEAN_EMAIL = {
    "subject": "Patch your VPN today",
    "preheader": "Attackers are scanning for it",
    "body": "Hello, apply the fix now.",
    "call_to_action": "Patch now",
}


def failed(results: list[Any]) -> set[str]:
    return {r.check for r in results if not r.passed}


def test_a_clean_asset_passes_every_check() -> None:
    results = check_asset("email_writer", [CLEAN_EMAIL], REPORT)

    assert {r.check for r in results} == set(CHECK_NAMES)
    assert failed(results) == set()


@pytest.mark.parametrize(
    "claim", ["100% protection", "We guarantee safety", "completely eliminates risk"]
)
def test_banned_claim_fails_on_absolute_claims(claim: str) -> None:
    draft = {**CLEAN_EMAIL, "body": f"Our product gives {claim}."}

    assert failed(check_asset("email_writer", [draft], REPORT)) == {"banned_claim"}


def test_off_brand_word_fails_on_hype_or_fear_words() -> None:
    page = {
        "headline": "A terrifying new threat",
        "subheadline": "",
        "body": "b",
        "call_to_action": "c",
    }

    assert failed(check_asset("landing_page", page, REPORT)) == {"off_brand_word"}


def test_length_fails_on_an_overlong_social_post() -> None:
    posts = {"posts": [{"channel": "x", "text": "a" * 400}]}

    assert failed(check_asset("social", posts, REPORT)) == {"length"}


def test_length_fails_on_an_overlong_subject() -> None:
    draft = {**CLEAN_EMAIL, "subject": "s" * 120}

    assert failed(check_asset("email_writer", [draft], REPORT)) == {"length"}


def test_checks_run_on_every_variant_of_an_asset() -> None:
    bad = {**CLEAN_EMAIL, "body": "We guarantee it."}

    assert failed(check_asset("email_writer", [CLEAN_EMAIL, bad], REPORT)) == {"banned_claim"}


def test_uncited_fact_fails_when_a_quote_is_not_on_the_cited_line() -> None:
    good = {
        "facts": [{"claim": "c", "line": 2, "quote": "Actors exploit unpatched VPN appliances."}]
    }
    bad = {
        "facts": [{"claim": "c", "line": 1, "quote": "Actors exploit unpatched VPN appliances."}]
    }

    assert failed(check_asset("research", good, REPORT)) == set()
    assert failed(check_asset("research", bad, REPORT)) == {"uncited_fact"}


def test_eval_length_limits_are_the_ones_the_writers_are_told() -> None:
    assert checks.MAX_CHARS == limits.MAX_CHARS
