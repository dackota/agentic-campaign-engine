"""`make load`: the load test. It starts N campaigns at once through the Campaign API, waits
until each one's drafting ends, and writes what it saw as JSON: cost per campaign, p50 and
p95 run time, the step cache hit rate, the runs lost, and the 429 replies.

It speaks only HTTP, so the depth is whatever the API behind it runs at. With no --api-url
it starts the harness stack (ACE_DEPTH picks fast or live depth) and signs in as a Demand
Gen owner; with one, it sends the token in ACE_API_TOKEN. The numbers for the live run go
in docs/load-test.md."""

import argparse
import json
import math
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_CAMPAIGNS = 20
DEFAULT_OUT = "load-test.json"
TOKEN_ENV = "ACE_API_TOKEN"
DEPTH_ENV = "ACE_DEPTH"
FAST_TIMEOUT_SECONDS = 120
LIVE_TIMEOUT_SECONDS = 1800
HTTP_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.5
TOO_MANY_REQUESTS = 429
AWAITING = "awaiting_approval"
FAILED = "failed"
DRAFTING_ENDED = (AWAITING, FAILED)
REPORT = (
    "Volt Typhoon targets edge routers\n"
    "Actors exploit unpatched VPN appliances to reach internal networks.\n"
    "Patch the appliances and rotate the credentials stored on them."
)


@dataclass(frozen=True)
class Run:
    """One campaign of the load: how it ended, how long drafting took, what it cost."""

    status: str
    seconds: float
    cost_usd: float = 0.0
    agent_steps: int = 0
    cache_hits: int = 0
    replies_429: int = 0
    failure_reason: str = ""


@dataclass(frozen=True)
class LoadResult:
    campaigns: int
    finished: int
    lost: int
    cost_per_campaign_usd: float
    total_cost_usd: float
    p50_seconds: float
    p95_seconds: float
    cache_hit_rate: float
    replies_429: int


def percentile(values: list[float], percent: float) -> float:
    """The nearest-rank percentile of `values`; 0 when there are none."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def _is_429_failure(run: Run) -> bool:
    return str(TOO_MANY_REQUESTS) in run.failure_reason


def summarize(runs: list[Run]) -> LoadResult:
    """The load's numbers. A run is lost unless its drafting ended waiting for approval. The
    429 count is the Campaign API's 429 replies plus the runs a model 429 stopped."""
    finished = [r for r in runs if r.status == AWAITING]
    steps = sum(r.agent_steps for r in runs)
    total_cost = sum(r.cost_usd for r in runs)
    return LoadResult(
        campaigns=len(runs),
        finished=len(finished),
        lost=len(runs) - len(finished),
        cost_per_campaign_usd=total_cost / len(runs) if runs else 0.0,
        total_cost_usd=total_cost,
        p50_seconds=percentile([r.seconds for r in finished], 50),
        p95_seconds=percentile([r.seconds for r in finished], 95),
        cache_hit_rate=sum(r.cache_hits for r in runs) / steps if steps else 0.0,
        replies_429=sum(r.replies_429 for r in runs) + sum(1 for r in runs if _is_429_failure(r)),
    )


class _Counted:
    """The API client, counting the 429 replies one campaign's calls got. A 429 is retried
    after the poll interval, so a busy API slows the run instead of losing it."""

    def __init__(self, api: httpx.Client, deadline: float) -> None:
        self._api = api
        self._deadline = deadline
        self.replies_429 = 0

    def call(self, send: Callable[[httpx.Client], httpx.Response]) -> httpx.Response:
        while True:
            response = send(self._api)
            if response.status_code != TOO_MANY_REQUESTS or time.monotonic() > self._deadline:
                return response
            self.replies_429 += 1
            time.sleep(POLL_INTERVAL_SECONDS)


def _run_one(api: httpx.Client, report: str, use_step_cache: bool, timeout: float) -> Run:
    """Create one campaign and wait until its drafting ends or `timeout` passes."""
    started = time.monotonic()
    client = _Counted(api, started + timeout)
    created = client.call(
        lambda a: a.post("/campaigns", json={"report": report, "use_step_cache": use_step_cache})
    )
    if created.status_code != httpx.codes.CREATED:
        return Run(f"create_failed_{created.status_code}", 0.0, replies_429=client.replies_429)
    campaign_id = created.json()["id"]
    body: dict[str, Any] = {"status": "unknown"}
    while time.monotonic() - started < timeout:
        response = client.call(lambda a: a.get(f"/campaigns/{campaign_id}"))
        response.raise_for_status()
        body = response.json()
        if body["status"] in DRAFTING_ENDED:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    seconds = time.monotonic() - started
    cost = body.get("cost") or {}
    steps = cost.get("steps") or []
    return Run(
        status=str(body["status"]),
        seconds=seconds,
        cost_usd=float(cost.get("cost_usd") or 0.0),
        agent_steps=len(steps),
        cache_hits=sum(1 for s in steps if s.get("cache_hit")),
        replies_429=client.replies_429,
        failure_reason=str(body.get("failure_reason") or ""),
    )


def run_load(
    api: httpx.Client, campaigns: int, report: str, use_step_cache: bool, timeout: float
) -> LoadResult:
    """Start `campaigns` campaigns at once, each on its own thread, and sum up the runs."""
    with ThreadPoolExecutor(max_workers=campaigns) as pool:
        futures = [
            pool.submit(_run_one, api, report, use_step_cache, timeout) for _ in range(campaigns)
        ]
        return summarize([f.result() for f in futures])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run campaigns at once and write the numbers.")
    parser.add_argument("--campaigns", type=int, default=DEFAULT_CAMPAIGNS)
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--api-url", help="a running Campaign API; none starts the stack")
    parser.add_argument("--report-file", type=Path, help="the threat report every campaign gets")
    parser.add_argument("--no-step-cache", action="store_true", help="turn the step cache off")
    parser.add_argument("--timeout", type=float, help="seconds a campaign may take to draft")
    return parser


def _default_timeout() -> float:
    return LIVE_TIMEOUT_SECONDS if os.environ.get(DEPTH_ENV) == "live" else FAST_TIMEOUT_SECONDS


def _load(api: httpx.Client, options: argparse.Namespace) -> int:
    if options.campaigns < 1:
        raise SystemExit("--campaigns must be at least 1")
    report = options.report_file.read_text() if options.report_file else REPORT
    timeout = options.timeout or _default_timeout()
    result = run_load(api, options.campaigns, report, not options.no_step_cache, timeout)
    options.out.write_text(json.dumps(asdict(result), indent=2) + "\n")
    print(json.dumps(asdict(result)))  # noqa: T201  the CLI's one line of output
    return 0 if result.lost == 0 else 1


def main(args: list[str], api: httpx.Client | None = None) -> int:
    """Run the load and write the result to --out. Exit 1 when a run was lost. `api` is a
    signed-in client to use instead of --api-url."""
    options = _parser().parse_args(args)
    if api is not None:
        return _load(api, options)
    if options.api_url:
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise SystemExit(f"{TOKEN_ENV} is required with --api-url")
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(
            base_url=options.api_url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
        ) as client:
            return _load(client, options)
    return _on_stack(options)


def _on_stack(options: argparse.Namespace) -> int:
    from tests.api.helpers import OWNER
    from tests.harness.stack import Stack

    with Stack() as stack:
        headers = {"Authorization": f"Bearer {stack.dex.token(OWNER)}"}
        with httpx.Client(
            base_url=stack.api_url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
        ) as client:
            return _load(client, options)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
