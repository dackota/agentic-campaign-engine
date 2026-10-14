"""Seam 1 at fast depth: the demo seed loads Acme Security's two teams with one finished
campaign each, through the Campaign API only. It repeats the same way: seeding twice on one stack
adds nothing and gives the same steps, assets and judge scores."""

import httpx

from tests.api.conftest import SignIn
from tests.harness import demo_seed

TEAMS = {"demand-gen", "product-marketing"}
OWNERS = ("dg-owner@demo.example", "pm-owner@demo.example")


def _titles(client: httpx.Client) -> list[str]:
    response = client.get("/campaigns")
    assert response.status_code == 200, response.text
    return [c["report"].splitlines()[0] for c in response.json()]


def test_seed_loads_acme_campaigns_for_both_teams(sign_in: SignIn) -> None:
    seeded = demo_seed.seed(sign_in)
    again = demo_seed.seed(sign_in)

    assert {s["team"] for s in seeded} == TEAMS
    for item in seeded:
        assert item["status"] == "sent"
        assert item["steps"], item
        assert item["scores"], item
        assert item["assets"]["email"], item
        assert item["assets"]["previews"]["email"], item
        assert all(score > 0 for score in item["scores"].values())
        assert "Acme Security" in item["title"]
    # Seeding again finds what is there: the same result, no second campaign.
    assert again == seeded
    # Row-level security: each team sees its own seeded campaign and not the other's.
    by_team = {s["team"]: s["title"] for s in seeded}
    dg_titles = _titles(sign_in(OWNERS[0]))
    pm_titles = _titles(sign_in(OWNERS[1]))
    assert dg_titles.count(by_team["demand-gen"]) == 1
    assert by_team["product-marketing"] not in dg_titles
    assert pm_titles.count(by_team["product-marketing"]) == 1
    assert by_team["demand-gen"] not in pm_titles
