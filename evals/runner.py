"""The eval runner: drives the Campaign API with each golden report and grades what the
campaign wrote. It speaks only HTTP, so it runs at fast depth in tests and at live depth
against the cluster: the depth is whatever the API behind it runs at."""

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from evals.agreement import LABELS_PATH, depth, load_labels, measure, write
from evals.campaign import AWAITING, create_and_wait
from evals.checks import CheckResult, check_asset, texts
from evals.gate import BASELINE_PATH, compare, load_baseline, render_verdict, write_baseline
from evals.golden import GoldenReport, load_golden
from evals.report import render

ASSET_STEPS = ("email_writer", "landing_page", "social", "one_pager")
RESEARCH_STEP = "research"
FAST_TIMEOUT_SECONDS = 30
LIVE_TIMEOUT_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 30
TOKEN_ENV = "ACE_API_TOKEN"
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
    judge_scores: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    agent_steps: int = 0

    @property
    def passed(self) -> bool:
        everything = self.assets + ([self.research] if self.research else [])
        return (
            not self.error
            and self.status == AWAITING
            and {a.step for a in self.assets} >= set(ASSET_STEPS)
            and self.research is not None
            and all(self.key_facts.values())
            and all(a.passed for a in everything)
        )


def _timeout_seconds() -> int:
    return LIVE_TIMEOUT_SECONDS if os.environ.get("ACE_DEPTH") == "live" else FAST_TIMEOUT_SECONDS


def _outputs(api: httpx.Client, campaign_id: str) -> dict[str, Any]:
    response = api.get(f"/campaigns/{campaign_id}/steps")
    response.raise_for_status()
    return {row["step"]: row["output"] for row in response.json()}


def _grade_step(entry: GoldenReport, step: str, outputs: dict[str, Any]) -> AssetResult:
    if step not in outputs:
        return AssetResult(step, [CheckResult("output_present", False, f"no output for {step}")])
    return AssetResult(step, check_asset(step, outputs[step], entry.report))


def _grade(entry: GoldenReport, body: dict[str, Any], outputs: dict[str, Any]) -> ReportResult:
    assets = [_grade_step(entry, step, outputs) for step in ASSET_STEPS]
    research = _grade_step(entry, RESEARCH_STEP, outputs)
    written = " ".join(
        t.lower() for step in (*ASSET_STEPS, RESEARCH_STEP) for t in texts(outputs.get(step))
    )
    key_facts = {fact: fact.lower() in written for fact in entry.key_facts}
    cost_steps = body.get("cost", {}).get("steps", [])
    return ReportResult(
        entry.id,
        str(body["status"]),
        key_facts,
        assets,
        research,
        judge_scores={s["step"]: s["score"] for s in body.get("scores", [])},
        cache_hits=sum(1 for s in cost_steps if s.get("cache_hit")),
        agent_steps=len(cost_steps),
    )


def run_golden(
    api: httpx.Client, golden: list[GoldenReport], timeout: float | None = None
) -> list[ReportResult]:
    """Create one campaign per golden report, wait for it to draft, and grade it."""
    wait = _timeout_seconds() if timeout is None else timeout
    return [_run_one(api, entry, wait) for entry in golden]


def _run_one(api: httpx.Client, entry: GoldenReport, wait: float) -> ReportResult:
    """One report's run; an HTTP failure becomes a failed result, not an aborted run."""
    try:
        campaign_id, body = create_and_wait(api, entry.report, wait)
        return _grade(entry, body, _outputs(api, campaign_id))
    except httpx.HTTPError as err:
        return ReportResult(entry.id, "error", {}, [], error=str(err))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evals", description="Run the golden set.")
    parser.add_argument("--api-url", default=os.environ.get(URL_ENV))
    parser.add_argument("--out", type=Path, help="also write the report to this file")
    parser.add_argument("--limit", type=int, help="run only the first N golden reports")
    parser.add_argument(
        "--baseline", type=Path, help="compare each report to this baseline; fail on a drop"
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the baseline (evals/baseline.json unless --baseline) from this run",
    )
    parser.add_argument("--labels", type=Path, default=LABELS_PATH, help="hand-labeled assets")
    parser.add_argument(
        "--agreement-out", type=Path, help="measure judge agreement and write it to this file"
    )
    return parser


def _gate_text(args: argparse.Namespace, results: list[ReportResult]) -> tuple[str, bool]:
    """The gate's text and whether it holds; the baseline is rewritten only on request."""
    path: Path | None = args.baseline or (BASELINE_PATH if args.update_baseline else None)
    if path is None:
        return "", True
    if args.update_baseline:
        write_baseline(path, results)
        return f"gate: baseline {path} updated from this run\n", True
    verdict = compare(load_baseline(path), results)
    return render_verdict(verdict), verdict.passed


def _cache_text(results: list[ReportResult]) -> str:
    hits = sum(r.cache_hits for r in results)
    steps = sum(r.agent_steps for r in results)
    return f"step cache: {hits} of {steps} agent steps reused, {steps - hits} called the model\n"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV)
    if not args.api_url or not token:
        parser.error(f"give --api-url (or {URL_ENV}) and set {TOKEN_ENV}")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    golden = load_golden()[: args.limit]
    errored = 0
    with httpx.Client(
        base_url=args.api_url,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {token}"},
    ) as api:
        results = run_golden(api, golden)
        if args.agreement_out:
            found = measure(api, load_labels(args.labels), _timeout_seconds())
            write(args.agreement_out, found, depth())
            errored = found.errored
    gate, holds = _gate_text(args, results)
    text = render(results) + _cache_text(results) + gate
    if args.out:
        args.out.write_text(text)
    sys.stdout.write(text)
    return 0 if results and holds and all(r.passed for r in results) and not errored else 1
