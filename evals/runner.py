"""The eval runner: drives the Campaign API with each golden report and grades what the
campaign wrote. It speaks only HTTP, so it runs at fast depth in tests and at live depth
against the cluster: the depth is whatever the API behind it runs at."""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from evals.checks import CheckResult, check_asset, texts
from evals.golden import GoldenReport, load_golden
from evals.report import render

ASSET_STEPS = ("email_writer", "landing_page", "social", "one_pager")
RESEARCH_STEP = "research"
# The seeded workflow every deployment has (ace_engine.default_workflow).
WORKFLOW = "threat-report-to-campaign"
AWAITING = "awaiting_approval"
FAILED = "failed"
FAST_TIMEOUT_SECONDS = 30
LIVE_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 0.5
HTTP_TIMEOUT_SECONDS = 30
TOKEN_ENV = "ACE_API_TOKEN"  # noqa: S105 - the name of the variable, not a secret
URL_ENV = "ACE_API_URL"


@dataclass(frozen=True)
class AssetResult:
    step: str
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


@dataclass(frozen=True)
class ReportResult:
    id: str
    status: str
    key_facts: dict[str, bool]
    assets: list[AssetResult]
    research: AssetResult | None = field(default=None)
    error: str = ""

    @property
    def passed(self) -> bool:
        everything = self.assets + ([self.research] if self.research else [])
        return (
            not self.error
            and self.status == AWAITING
            and {a.step for a in self.assets} >= set(ASSET_STEPS)
            and all(self.key_facts.values())
            and all(a.passed for a in everything)
        )


def _timeout_seconds() -> int:
    return LIVE_TIMEOUT_SECONDS if os.environ.get("ACE_DEPTH") == "live" else FAST_TIMEOUT_SECONDS


def _wait(api: httpx.Client, campaign_id: str, timeout: float) -> str:
    """Poll until drafting ends; the last status seen if it never does."""
    deadline = time.monotonic() + timeout
    status = "unknown"
    while time.monotonic() < deadline:
        response = api.get(f"/campaigns/{campaign_id}")
        response.raise_for_status()
        status = str(response.json()["status"])
        if status in (AWAITING, FAILED):
            return status
        time.sleep(POLL_INTERVAL_SECONDS)
    return status


def _outputs(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    response = api.get(f"/campaigns/{campaign_id}/steps")
    response.raise_for_status()
    return {row["step"]: row["output"] for row in response.json()}


def _grade_step(entry: GoldenReport, step: str, outputs: dict[str, Any]) -> AssetResult:
    if step not in outputs:
        return AssetResult(step, [CheckResult("output_present", False, f"no output for {step}")])
    return AssetResult(step, check_asset(step, outputs[step], entry.report))


def _grade(entry: GoldenReport, status: str, outputs: dict[str, Any]) -> ReportResult:
    assets = [_grade_step(entry, step, outputs) for step in ASSET_STEPS]
    research = (
        AssetResult(RESEARCH_STEP, check_asset(RESEARCH_STEP, outputs[RESEARCH_STEP], entry.report))
        if RESEARCH_STEP in outputs
        else None
    )
    written = " ".join(
        t.lower() for step in (*ASSET_STEPS, RESEARCH_STEP) for t in texts(outputs.get(step))
    )
    key_facts = {fact: fact.lower() in written for fact in entry.key_facts}
    return ReportResult(entry.id, status, key_facts, assets, research)


def run_golden(
    api: httpx.Client, golden: list[GoldenReport], timeout: float | None = None
) -> list[ReportResult]:
    """Create one campaign per golden report, wait for it to draft, and grade it."""
    wait = _timeout_seconds() if timeout is None else timeout
    return [_run_one(api, entry, wait) for entry in golden]


def _run_one(api: httpx.Client, entry: GoldenReport, wait: float) -> ReportResult:
    """One report's run; an HTTP failure becomes a failed result, not an aborted run."""
    try:
        created = api.post("/campaigns", json={"report": entry.report, "workflow": WORKFLOW})
        created.raise_for_status()
        campaign_id = created.json()["id"]
        status = _wait(api, campaign_id, wait)
        return _grade(entry, status, _outputs(api, campaign_id))
    except httpx.HTTPError as err:
        return ReportResult(entry.id, "error", {}, [], error=str(err))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description="Run the golden set.")
    parser.add_argument("--api-url", default=os.environ.get(URL_ENV))
    parser.add_argument("--out", type=Path, help="also write the report to this file")
    parser.add_argument("--limit", type=int, help="run only the first N golden reports")
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV)
    if not args.api_url or not token:
        parser.error(f"give --api-url (or {URL_ENV}) and set {TOKEN_ENV}")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    golden = load_golden()[: args.limit]
    with httpx.Client(
        base_url=args.api_url,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {token}"},
    ) as api:
        results = run_golden(api, golden)
    text = render(results)
    if args.out:
        args.out.write_text(text)
    sys.stdout.write(text)
    return 0 if results and all(r.passed for r in results) else 1
