"""The quality report is plain text a person can read."""

from evals.checks import CheckResult
from evals.report import render
from evals.runner import AssetResult, ReportResult


def test_report_lists_key_facts_and_check_results_per_asset() -> None:
    result = ReportResult(
        id="volt-typhoon",
        status="awaiting_approval",
        key_facts={"edge routers": True, "VPN appliances": False},
        assets=[
            AssetResult("email_writer", [CheckResult("banned_claim", False, "found '100%'")]),
            AssetResult("social", [CheckResult("length", True, "")]),
        ],
    )

    text = render([result])

    assert "volt-typhoon" in text
    assert "found: edge routers" in text
    assert "missing: VPN appliances" in text
    assert "email_writer" in text
    assert "FAIL banned_claim" in text
    assert "found '100%'" in text
    assert "PASS length" in text
    assert "1 of 1 reports failed" in text


def test_report_with_fewer_than_four_asset_steps_does_not_pass() -> None:
    result = ReportResult(
        id="r",
        status="awaiting_approval",
        key_facts={},
        assets=[AssetResult("email_writer", [CheckResult("length", True, "")])],
    )

    assert not result.passed
