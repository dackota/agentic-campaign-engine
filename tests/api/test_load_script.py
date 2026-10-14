"""Seam 1, fast depth: the load-test script runs campaigns at once through the Campaign API
and writes cost per campaign, p50 and p95 run time, the cache hit rate, and the 429 count. How it
counts a lost run, a model 429 and a missed deadline is proved without a stack:
tests/harness/test_load_errors.py."""

import json
from pathlib import Path

import httpx

from tests.harness import load

# Enough for later campaigns to reuse the earlier ones' saved steps.
CAMPAIGNS = 3


def test_load_script_runs_campaigns_at_once_and_writes_the_numbers(
    api: httpx.Client, tmp_path: Path
) -> None:
    out = tmp_path / "load.json"

    exit_code = load.main(["--campaigns", str(CAMPAIGNS), "--out", str(out)], api=api)

    written = json.loads(out.read_text())
    assert exit_code == 0
    assert written["campaigns"] == CAMPAIGNS
    assert written["finished"] == CAMPAIGNS
    assert written["lost"] == 0
    assert written["replies_429"] == 0
    # The scripted agent bills every call, so a campaign costs something.
    assert written["cost_per_campaign_usd"] > 0
    assert 0 < written["p50_seconds"] <= written["p95_seconds"]
    # The campaigns share one report: the later ones reuse the earlier ones' saved steps.
    assert 0 < written["cache_hit_rate"] <= 1
