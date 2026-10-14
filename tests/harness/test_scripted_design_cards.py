"""The scripted design step answers with the same two cards for every report, and they meet
the cards contract."""

from ace_engine.contracts import DESIGN_CARDS_SCHEMA, violations

from tests.support.scripted_outputs import scripted_output

CARD_NAMES = ["social-card-1.svg", "social-card-2.svg"]


def test_the_design_step_returns_the_same_two_cards_for_any_report() -> None:
    first = scripted_output("design", report="one report")
    second = scripted_output("design", report="a quite different report")

    assert first == second
    assert [c["name"] for c in first["cards"]] == CARD_NAMES
    assert all(c["svg"].startswith("<svg") for c in first["cards"])


def test_the_design_cards_meet_the_cards_contract() -> None:
    assert violations(scripted_output("design"), DESIGN_CARDS_SCHEMA) == []
