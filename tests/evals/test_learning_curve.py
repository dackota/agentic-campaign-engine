"""Seam 1: the learning-curve script drives the Campaign API. It runs campaigns in a row
against the fake Marketo's simulated audience, records each one's click rate, and writes a
trend chart and a table. With learnings off it deletes each learning as soon as the winner is
called, so the next campaign's agents find none. Fast depth here, with the scripted agent;
the real numbers come from a live run (docs/learning-proof.md)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from evals.learning_curve import (
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

    result = subprocess.run(
        [sys.executable, "-m", "evals.learning_curve", "--api-url", stack.api_url]
        + ["--campaigns", "2", "--quiet-seconds", str(QUIET), "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    chart = (tmp_path / "trend.svg").read_text()
    assert chart.startswith("<svg")
    assert chart.count("<polyline") == 2  # one line per run
    assert chart.count("<circle") == 4  # one point per campaign per run
    assert "learnings on" in chart and "learnings off" in chart
    points = re.search(r'<polyline[^>]*points="([^"]+)"', chart)
    assert points and len(points.group(1).split()) == 2
    table = (tmp_path / "results.md").read_text()
    assert "learnings on" in table and "learnings off" in table
    assert table.count("| 1 |") == 2 and table.count("| 2 |") == 2
    results = json.loads((tmp_path / "results.json").read_text())
    assert {k: len(v) for k, v in results.items()} == {"learnings on": 2, "learnings off": 2}
    for rows in results.values():
        for row in rows:
            assert f"{row['click_rate']:.1%}" in table
