"""Seam 1: the learning-curve script drives the Campaign API. It runs campaigns in a row
against the fake Marketo's simulated audience, records each one's click rate, and writes a
trend chart and a table. With learnings off it deletes each learning as soon as the winner is
called, so the next campaign's agents find none. Fast depth here, with the scripted agent;
the real numbers come from a live run (docs/learning-proof.md)."""

import re
from pathlib import Path

import httpx
import pytest

from evals.learning_curve import (
    CampaignRate,
    main,
    render_chart,
    render_table,
    run_campaigns,
)
from tests.api.conftest import SignIn
from tests.api.helpers import APPROVER, DAY_SPEED, OWNER
from tests.harness.stack import Stack

SEED = 1  # a seed whose audience calls an A/B winner
FIVE = 5
QUIET = 0.8


def kept(api: httpx.Client, campaign_ids: list[str]) -> list[str]:
    """The campaign ids among `campaign_ids` that still have a learning."""
    response = api.get("/learnings")
    assert response.status_code == 200, response.text
    return [i["campaign_id"] for i in response.json() if i["campaign_id"] in campaign_ids]


@pytest.fixture
def audience(stack: Stack) -> None:
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)


def test_runs_five_campaigns_in_a_row_and_records_a_click_rate_each(
    audience: None, api: httpx.Client, approver: httpx.Client
) -> None:
    rates = run_campaigns(api, approver, FIVE, learnings_on=True, quiet_seconds=QUIET)

    assert len(rates) == FIVE
    assert len({r.campaign_id for r in rates}) == FIVE
    assert all(r.opens > 0 and r.clicks > 0 for r in rates)
    assert all(r.click_rate == pytest.approx(r.clicks / r.opens) for r in rates)
    assert all(r.winner in ("A", "B") for r in rates)


def test_learnings_on_keeps_the_learnings(
    audience: None, api: httpx.Client, approver: httpx.Client
) -> None:
    rates = run_campaigns(api, approver, 2, learnings_on=True, quiet_seconds=QUIET)

    ids = [r.campaign_id for r in rates]
    assert len(ids) == 2
    assert sorted(kept(api, ids)) == sorted(ids)


def test_learnings_off_deletes_each_learning_so_none_is_kept(
    audience: None, api: httpx.Client, approver: httpx.Client
) -> None:
    rates = run_campaigns(api, approver, 3, learnings_on=False, quiet_seconds=QUIET)

    assert len(rates) == 3
    assert kept(api, [r.campaign_id for r in rates]) == []


def rate(index: int, click_rate: float) -> CampaignRate:
    return CampaignRate(f"id-{index}", "A", 100, round(click_rate * 100), click_rate)


def test_chart_rises_with_the_rates() -> None:
    svg = render_chart({"learnings on": [rate(i, 0.1 * (i + 1)) for i in range(FIVE)]})

    points = re.search(r'<polyline[^>]*points="([^"]+)"', svg)
    assert svg.startswith("<svg") and points
    ys = [float(p.split(",")[1]) for p in points.group(1).split()]
    assert len(ys) == FIVE
    assert ys == sorted(ys, reverse=True)  # SVG y grows downward: a rising rate falls in y
    assert ys[0] > ys[-1]
    assert "learnings on" in svg


def test_chart_draws_both_runs() -> None:
    flat = [rate(i, 0.2) for i in range(FIVE)]
    svg = render_chart({"learnings on": flat, "learnings off": flat})

    assert svg.count("<polyline") == 2


def test_table_lists_every_campaign_for_both_runs() -> None:
    table = render_table(
        {
            "learnings on": [rate(0, 0.1), rate(1, 0.3)],
            "learnings off": [rate(0, 0.1), rate(1, 0.1)],
        }
    )

    assert "learnings on" in table and "learnings off" in table
    assert "30.0%" in table and "10.0%" in table
    assert table.count("| 1 |") == 2 and table.count("| 2 |") == 2


def test_cli_writes_chart_table_and_results_for_both_runs(
    stack: Stack,
    audience: None,
    sign_in: SignIn,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stack.agent.script([])
    monkeypatch.setenv("ACE_API_TOKEN", stack.dex.token(OWNER))
    monkeypatch.setenv("ACE_APPROVER_TOKEN", stack.dex.token(APPROVER))

    code = main(
        ["--api-url", stack.api_url, "--campaigns", "2", "--quiet-seconds", str(QUIET)]
        + ["--out-dir", str(tmp_path)]
    )

    assert code == 0
    chart = (tmp_path / "trend.svg").read_text()
    assert chart.count("<polyline") == 2
    table = (tmp_path / "results.md").read_text()
    assert "learnings on" in table and "learnings off" in table
    assert (tmp_path / "results.json").exists()
