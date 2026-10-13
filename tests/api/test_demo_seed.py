"""Seam 1 at fast depth: the demo seed loads Acme Security's two teams with one finished
campaign each, through the Campaign API only. It repeats the same way: two clean stacks give
the same steps, assets and judge scores, and seeding twice on one stack adds nothing."""

import httpx
import pytest

from tests.api.conftest import SignIn
from tests.harness import demo_seed
from tests.harness.stack import Stack

TEAMS = {"demand-gen", "product-marketing"}


def _titles(client: httpx.Client) -> list[str]:
    response = client.get("/campaigns")
    assert response.status_code == 200, response.text
    return [c["report"].splitlines()[0] for c in response.json()]


def test_seed_loads_acme_campaigns_for_both_teams(sign_in: SignIn) -> None:
    seeded = demo_seed.seed(sign_in)

    assert {s["team"] for s in seeded} == TEAMS
    for item in seeded:
        assert item["status"] == "sent"
        assert item["steps"], item
        assert item["scores"], item
        assert item["assets"]["email"], item
        assert item["assets"]["previews"]["email"], item
        assert all(score > 0 for score in item["scores"].values())
        assert "Acme Security" in item["title"]
    # Row-level security: each team sees its own seeded campaign and not the other's.
    by_team = {s["team"]: s["title"] for s in seeded}
    dg_titles = _titles(sign_in("dg-owner@demo.example"))
    pm_titles = _titles(sign_in("pm-owner@demo.example"))
    assert by_team["demand-gen"] in dg_titles
    assert by_team["product-marketing"] not in dg_titles
    assert by_team["product-marketing"] in pm_titles
    assert by_team["demand-gen"] not in pm_titles


def test_seeding_twice_on_one_stack_makes_no_duplicates(sign_in: SignIn) -> None:
    first = demo_seed.seed(sign_in)
    second = demo_seed.seed(sign_in)

    assert second == first
    for email in ("dg-owner@demo.example", "pm-owner@demo.example"):
        titles = _titles(sign_in(email))
        for item in first:
            assert titles.count(item["title"]) <= 1, (email, item["title"])
    assert sum(_titles(sign_in("dg-owner@demo.example")).count(s["title"]) for s in first) == 1


def test_seeding_two_clean_stacks_gives_the_same_result(sign_in: SignIn) -> None:
    on_first = demo_seed.seed(sign_in)

    with Stack() as clean:
        on_second = demo_seed.seed(_sign_in_on(clean))

    assert on_first
    assert on_second == on_first


def _sign_in_on(stack: Stack) -> SignIn:
    from tests.harness.api_client import api_client

    def client_for(email: str) -> httpx.Client:
        return api_client(stack.api_url, stack.dex.token(email))

    return client_for


def _preview_client(statuses: dict[str, int]) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        kind = request.url.path.rsplit("/preview", 1)[1].lstrip("/") or "email"
        return httpx.Response(statuses.get(kind, 200), text="secret-body")

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(answer))


def test_a_preview_with_no_content_is_skipped_and_another_failure_raises() -> None:
    campaign = {"id": "c1", "draft": {"subject": "s"}, "variant_b": None}

    with _preview_client({"social": 409}) as client:
        assets = demo_seed._assets(client, campaign)
    assert "social" not in assets["previews"]
    assert "email" in assets["previews"]

    with _preview_client({"cards": 500}) as client:
        with pytest.raises(RuntimeError) as failed:
            demo_seed._assets(client, campaign)
    assert "cards" in str(failed.value)
    assert "500" in str(failed.value)
    assert "secret-body" not in str(failed.value)
