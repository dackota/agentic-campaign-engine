"""Seam 1, fast depth: the load-test script runs campaigns at once through the Campaign API
and writes cost per campaign, p50 and p95 run time, the cache hit rate, and the 429 count."""

import json
from pathlib import Path

import httpx

from tests.harness import load

CAMPAIGNS = 20


def test_load_script_runs_twenty_campaigns_and_writes_the_numbers(
    api: httpx.Client, tmp_path: Path
) -> None:
    out = tmp_path / "load.json"

    exit_code = load.main(
        ["--campaigns", str(CAMPAIGNS), "--out", str(out)],
        api=api,
    )

    written = json.loads(out.read_text())
    assert exit_code == 0
    assert written["campaigns"] == CAMPAIGNS
    assert written["finished"] == CAMPAIGNS
    assert written["lost"] == 0
    assert written["replies_429"] == 0
    # The scripted agent bills every call, so a campaign costs something.
    assert written["cost_per_campaign_usd"] > 0
    assert 0 < written["p50_seconds"] <= written["p95_seconds"]
    # Twenty campaigns on one report: the later ones reuse the earlier ones' saved steps.
    assert 0 < written["cache_hit_rate"] <= 1


def test_only_a_model_rate_limit_counts_as_a_429_failure() -> None:
    rate_limited = load.Run(
        load.FAILED,
        1.0,
        failure_reason='step "draft" failed: llm error: "429 Too Many Requests"',
    )
    other = load.Run(load.FAILED, 1.0, failure_reason="budget of $4.2900 reached: id 14290")

    result = load.summarize([rate_limited, other])

    assert result.replies_429 == 1
    assert result.lost == 2
