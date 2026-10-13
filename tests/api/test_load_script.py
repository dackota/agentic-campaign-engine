"""Seam 1, fast depth: the load-test script runs campaigns at once through the Campaign API
and writes cost per campaign, p50 and p95 run time, the cache hit rate, and the 429 count."""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.harness import load
from tests.harness.stack import free_port

CAMPAIGNS = 20
# Long enough for a step to fail its three attempts at fast depth.
FAILING_TIMEOUT = 60
DEADLINE_SECONDS = 1


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


def _load_one(api: httpx.Client, tmp_path: Path, report: str, timeout: int) -> dict[str, Any]:
    """Run the load script on one campaign with `report`; the JSON it wrote."""
    report_file, out = tmp_path / "report.txt", tmp_path / "load.json"
    report_file.write_text(report)

    exit_code = load.main(
        ["--campaigns", "1", "--report-file", str(report_file), "--out", str(out)]
        + ["--timeout", str(timeout), "--no-step-cache"],
        api=api,
    )

    written: dict[str, Any] = json.loads(out.read_text())
    assert exit_code == 1, "a lost run fails the load"
    return written


def _unique(marker: str) -> str:
    # The scripted agent counts a marker's failures per report, so each test needs its own.
    return f"Load check {uuid.uuid4().hex}\nActors exploit unpatched VPN appliances. {marker}"


def test_a_run_the_model_gateway_rate_limited_counts_as_a_429(
    api: httpx.Client, tmp_path: Path
) -> None:
    written = _load_one(api, tmp_path, _unique("[agent:task-failed-99]"), FAILING_TIMEOUT)

    assert written["lost"] == 1
    assert written["replies_429"] == 1
    assert "429 Too Many Requests" in written["lost_reasons"][0]


def test_a_run_lost_for_another_reason_is_not_a_429(api: httpx.Client, tmp_path: Path) -> None:
    written = _load_one(api, tmp_path, _unique("[agent:down-99]"), FAILING_TIMEOUT)

    assert written["lost"] == 1
    assert written["replies_429"] == 0
    assert "agent unavailable" in written["lost_reasons"][0]


def test_a_run_that_misses_the_deadline_is_lost_with_its_reason(
    api: httpx.Client, tmp_path: Path
) -> None:
    # The slow marker holds each agent reply, so drafting cannot end in time.
    written = _load_one(api, tmp_path, _unique("[agent:slow]"), DEADLINE_SECONDS)

    assert written["lost"] == 1
    assert written["replies_429"] == 0
    assert written["lost_reasons"][0].startswith(f"drafting did not end within {DEADLINE_SECONDS}s")


def test_an_unreachable_api_loses_every_run_and_still_writes_the_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "load.json"
    monkeypatch.setenv(load.TOKEN_ENV, "not-a-real-token")
    # Nothing listens on a port that was free a moment ago.
    dead_api = f"http://127.0.0.1:{free_port()}"

    exit_code = load.main(
        ["--campaigns", "2", "--api-url", dead_api, "--out", str(out), "--timeout", "5"]
    )

    written = json.loads(out.read_text())
    assert exit_code == 1
    assert written["lost"] == 2
    assert written["finished"] == 0
    assert all(r.startswith("ConnectError") for r in written["lost_reasons"])
