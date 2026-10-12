"""Seam 1: the eval runner drives the Campaign API. Fast depth here, with the scripted
agent; the real run is at live depth on k3d-ace."""

from pathlib import Path

import httpx
import pytest

from evals.golden import GoldenReport
from evals.runner import main, run_golden
from tests.api.helpers import OWNER
from tests.harness.stack import Stack

SAFE = GoldenReport(
    id="safe",
    report="Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.",
    key_facts=("edge routers", "unpatched VPN appliances"),
)
PLANTED = GoldenReport(
    id="planted",
    report="Volt Typhoon targets edge routers\nOur agent gives 100% protection against it.",
    key_facts=("edge routers", "a fact the report never states"),
)


def test_runner_drives_the_campaign_api_and_reports_per_report(api: httpx.Client) -> None:
    [result] = run_golden(api, [SAFE])

    assert result.id == "safe"
    assert result.status == "awaiting_approval"
    assert result.key_facts == {"edge routers": True, "unpatched VPN appliances": True}
    assert {a.step for a in result.assets} == {
        "email_writer",
        "landing_page",
        "social",
        "one_pager",
    }
    assert all(c.passed for a in result.assets for c in a.checks)


def test_planted_asset_that_fails_a_hard_check_shows_failed_in_the_report(
    api: httpx.Client,
) -> None:
    [result] = run_golden(api, [PLANTED])

    failed = {(a.step, c.check) for a in result.assets for c in a.checks if not c.passed}
    assert ("email_writer", "banned_claim") in failed
    assert result.key_facts["a fact the report never states"] is False
    assert not result.passed


def test_cli_writes_the_report_file(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack.agent.script([])
    monkeypatch.setenv("ACE_API_TOKEN", stack.dex.token(OWNER))
    out = tmp_path / "report.txt"

    code = main(["--api-url", stack.api_url, "--out", str(out), "--limit", "1"])

    text = out.read_text()
    assert code in (0, 1)
    assert "email_writer" in text
    assert "reports failed" in text
