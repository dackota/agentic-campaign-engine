"""Seam 1: the eval runner drives the Campaign API. Fast depth here, with the scripted
agent; the real run is at live depth on k3d-ace."""

from pathlib import Path

import httpx
import pytest

from evals.golden import GoldenReport
from evals.report import render
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


def _mock_api(handler: "httpx.MockTransport") -> httpx.Client:
    return httpx.Client(base_url="http://api.test", transport=handler)


def test_asset_step_missing_from_the_output_is_a_visible_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "c1"})
        if request.url.path.endswith("/steps"):
            return httpx.Response(
                200,
                json=[
                    {"step": s, "output": {"text": "Edge routers are exposed."}}
                    for s in ("email_writer", "landing_page", "social")
                ],
            )
        return httpx.Response(200, json={"status": "awaiting_approval"})

    [result] = run_golden(_mock_api(httpx.MockTransport(respond)), [SAFE], timeout=5)

    [missing] = [a for a in result.assets if a.step == "one_pager"]
    assert [(c.check, c.passed, c.detail) for c in missing.checks] == [
        ("output_present", False, "no output for one_pager")
    ]
    assert not result.passed
    assert "FAIL output_present: no output for one_pager" in render([result])


def test_http_error_for_one_report_is_a_fail_row_and_the_run_goes_on() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = request.content.decode()
            if "100%" in body:
                return httpx.Response(500, json={"detail": "boom"})
            return httpx.Response(200, json={"id": "c1"})
        if request.url.path.endswith("/steps"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "awaiting_approval"})

    results = run_golden(_mock_api(httpx.MockTransport(respond)), [PLANTED, SAFE], timeout=5)

    assert [r.id for r in results] == ["planted", "safe"]
    assert not results[0].passed
    assert "500" in results[0].error
    text = render(results)
    assert "FAIL planted" in text
    assert "error:" in text


def test_limit_below_one_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACE_API_TOKEN", "t")
    with pytest.raises(SystemExit) as exc:
        main(["--api-url", "http://api.test", "--limit", "0"])
    assert exc.value.code == 2


def test_main_returns_one_when_no_report_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACE_API_TOKEN", "t")
    monkeypatch.setattr("evals.runner.load_golden", lambda: [])
    assert main(["--api-url", "http://api.test"]) == 1


def test_research_step_missing_from_the_output_is_a_visible_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "c1"})
        if request.url.path.endswith("/steps"):
            return httpx.Response(
                200,
                json=[
                    {"step": s, "output": {"text": "Edge routers are exposed."}}
                    for s in ("email_writer", "landing_page", "social", "one_pager")
                ],
            )
        return httpx.Response(200, json={"status": "awaiting_approval"})

    [result] = run_golden(_mock_api(httpx.MockTransport(respond)), [SAFE], timeout=5)

    assert result.research is not None
    assert [(c.check, c.passed, c.detail) for c in result.research.checks] == [
        ("output_present", False, "no output for research")
    ]
    assert not result.passed
    assert "FAIL output_present: no output for research" in render([result])
