"""The learning curve: does the feedback loop make each campaign click better than the last?

It runs campaigns in a row through the Campaign API, approves each, lets the fake Marketo's
simulated audience open and click, and records the click rate (clicks over opens). Learnings
come from the audience itself: a called A/B winner becomes a learning the next campaign's
agents search (docs/decisions/learnings-store.md). With learnings off, the script deletes
each learning as soon as the campaign has settled, so the agents never find one
(docs/decisions/learnings-off.md).

It speaks only HTTP, so it runs at fast depth in tests and at live depth on the cluster; the
depth is whatever the API behind it runs at. See docs/learning-proof.md.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from evals.golden import load_golden

AWAITING = "awaiting_approval"
FAILED = "failed"
SENT = "sent"
LABEL_ON = "learnings on"
LABEL_OFF = "learnings off"
FAST_TIMEOUT_SECONDS = 60
LIVE_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 0.25
HTTP_TIMEOUT_SECONDS = 30
DEFAULT_CAMPAIGNS = 5
# How long engagement must hold still before a campaign counts as settled. The audience's
# days arrive in seconds (the fake's time speed), so a quiet stretch means they have all come.
DEFAULT_QUIET_SECONDS = 3.0
TOKEN_ENV = "ACE_API_TOKEN"
APPROVER_TOKEN_ENV = "ACE_APPROVER_TOKEN"
URL_ENV = "ACE_API_URL"


@dataclass(frozen=True)
class CampaignRate:
    campaign_id: str
    winner: str | None
    opens: int
    clicks: int
    click_rate: float


def _timeout_seconds() -> int:
    return LIVE_TIMEOUT_SECONDS if os.environ.get("ACE_DEPTH") == "live" else FAST_TIMEOUT_SECONDS


def _get(api: httpx.Client, path: str) -> Any:  # noqa: ANN401 - JSON of any shape
    response = api.get(path)
    response.raise_for_status()
    return response.json()


def _until(api: httpx.Client, campaign_id: str, wanted: tuple[str, ...], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    status = "unknown"
    while time.monotonic() < deadline:
        status = str(_get(api, f"/campaigns/{campaign_id}")["status"])
        if status == FAILED and FAILED not in wanted:
            raise RuntimeError(f"campaign {campaign_id} failed")
        if status in wanted:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"campaign {campaign_id} never reached {wanted}; last status {status}")


def _totals(engagement: dict[str, dict[str, int]]) -> tuple[int, int]:
    opens = sum(v.get("opens", 0) for v in engagement.values())
    clicks = sum(v.get("clicks", 0) for v in engagement.values())
    return opens, clicks


def _settled(api: httpx.Client, campaign_id: str, quiet: float, timeout: float) -> CampaignRate:
    """Wait until the audience has stopped engaging: opens and clicks unchanged for `quiet`
    seconds, with at least one open. Then read the campaign's rate."""
    deadline = time.monotonic() + timeout
    last: tuple[int, int] = (-1, -1)
    still_since = time.monotonic()
    while True:
        campaign = _get(api, f"/campaigns/{campaign_id}")
        totals = _totals(campaign["engagement"])
        now = time.monotonic()
        if totals != last:
            last, still_since = totals, now
        if totals[0] > 0 and now - still_since >= quiet:
            opens, clicks = totals
            return CampaignRate(
                campaign_id, campaign["ab_result"].get("winner"), opens, clicks, clicks / opens
            )
        if now >= deadline:
            raise TimeoutError(f"campaign {campaign_id} got no engagement; last {totals}")
        time.sleep(POLL_INTERVAL_SECONDS)


def _forget_learnings(api: httpx.Client, approver: httpx.Client, campaign_id: str) -> None:
    for learning in _get(api, "/learnings"):
        if learning["campaign_id"] == campaign_id:
            approver.delete(f"/learnings/{learning['id']}").raise_for_status()


def _run_one(
    api: httpx.Client,
    approver: httpx.Client,
    report: str,
    learnings_on: bool,
    quiet_seconds: float,
) -> CampaignRate:
    timeout = _timeout_seconds()
    created = api.post("/campaigns", json={"report": report})
    created.raise_for_status()
    campaign_id = str(created.json()["id"])
    _until(api, campaign_id, (AWAITING,), timeout)
    approver.post(f"/campaigns/{campaign_id}/approve").raise_for_status()
    _until(api, campaign_id, (SENT,), timeout)
    rate = _settled(api, campaign_id, quiet_seconds, timeout)
    if not learnings_on:
        _forget_learnings(api, approver, campaign_id)
    return rate


def run_campaigns(
    api: httpx.Client,
    approver: httpx.Client,
    count: int,
    *,
    learnings_on: bool,
    quiet_seconds: float = DEFAULT_QUIET_SECONDS,
) -> list[CampaignRate]:
    """Run `count` campaigns one after another, each on the next golden report. `api` is a
    team owner; `approver` approves the sends and deletes learnings when they are off."""
    golden = load_golden()
    return [
        _run_one(api, approver, golden[i % len(golden)].report, learnings_on, quiet_seconds)
        for i in range(count)
    ]


# Chart geometry, in SVG user units.
WIDTH, HEIGHT = 640, 360
LEFT, RIGHT, TOP, BOTTOM = 70, 30, 40, 60
COLORS = ("#1f77b4", "#d62728")
GRID_LINES = 4


def _y_max(series: dict[str, list[CampaignRate]]) -> float:
    top = max((r.click_rate for rates in series.values() for r in rates), default=0.0)
    return max(0.1, ((int(top * 10)) + 1) / 10)


def render_chart(series: dict[str, list[CampaignRate]]) -> str:
    """An SVG line chart: click rate by campaign number, one line per run."""
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    y_max = _y_max(series)
    longest = max((len(rates) for rates in series.values()), default=0)

    def x_at(index: int) -> float:
        return LEFT + (plot_w * index / (longest - 1) if longest > 1 else plot_w / 2)

    def y_at(rate: float) -> float:
        return TOP + plot_h * (1 - rate / y_max)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="sans-serif" font-size="12">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="white"/>',
        f'<text x="{WIDTH / 2}" y="22" text-anchor="middle" font-size="15">'
        "Click rate by campaign</text>",
    ]
    for step in range(GRID_LINES + 1):
        value = y_max * step / GRID_LINES
        y = y_at(value)
        parts.append(
            f'<line x1="{LEFT}" y1="{y:.1f}" x2="{WIDTH - RIGHT}" y2="{y:.1f}" stroke="#ddd"/>'
        )
        parts.append(f'<text x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{value:.0%}</text>')
    for index in range(longest):
        x = x_at(index)
        parts.append(
            f'<text x="{x:.1f}" y="{HEIGHT - BOTTOM + 20}" text-anchor="middle">{index + 1}</text>'
        )
    parts.append(
        f'<text x="{LEFT + plot_w / 2}" y="{HEIGHT - 20}" text-anchor="middle">campaign</text>'
    )
    for n, (label, rates) in enumerate(series.items()):
        color = COLORS[n % len(COLORS)]
        points = " ".join(f"{x_at(i):.1f},{y_at(r.click_rate):.1f}" for i, r in enumerate(rates))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{points}"/>')
        for i, r in enumerate(rates):
            parts.append(
                f'<circle cx="{x_at(i):.1f}" cy="{y_at(r.click_rate):.1f}" r="3" fill="{color}"/>'
            )
        legend_y = TOP + 14 + 16 * n
        parts.append(
            f'<rect x="{LEFT + 10}" y="{legend_y - 9}" width="12" height="12" fill="{color}"/>'
        )
        parts.append(f'<text x="{LEFT + 28}" y="{legend_y + 2}">{label}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_table(runs: dict[str, list[CampaignRate]]) -> str:
    """One markdown table per run: each campaign's opens, clicks, and click rate."""
    lines: list[str] = []
    for label, rates in runs.items():
        lines += [
            f"### {label}",
            "",
            "| # | campaign | winner | opens | clicks | click rate |",
            "|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(rates, start=1):
            lines.append(
                f"| {i} | {r.campaign_id} | {r.winner or '-'} | {r.opens} | {r.clicks} "
                f"| {r.click_rate:.1%} |"
            )
        lines.append("")
    return "\n".join(lines)


def _client(url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=url, timeout=HTTP_TIMEOUT_SECONDS, headers={"Authorization": f"Bearer {token}"}
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evals.learning_curve", description="Run campaigns in a row and chart click rate."
    )
    parser.add_argument("--api-url", default=os.environ.get(URL_ENV))
    parser.add_argument("--campaigns", type=int, default=DEFAULT_CAMPAIGNS)
    parser.add_argument("--learnings", choices=("on", "off", "both"), default="both")
    parser.add_argument("--quiet-seconds", type=float, default=DEFAULT_QUIET_SECONDS)
    parser.add_argument("--out-dir", type=Path, default=Path("learning-curve"))
    args = parser.parse_args(argv)
    owner_token, approver_token = os.environ.get(TOKEN_ENV), os.environ.get(APPROVER_TOKEN_ENV)
    if not args.api_url or not owner_token or not approver_token:
        parser.error(f"give --api-url (or {URL_ENV}) and set {TOKEN_ENV} and {APPROVER_TOKEN_ENV}")
    if args.campaigns < 1:
        parser.error("--campaigns must be at least 1")
    modes = {"on": [True], "off": [False], "both": [True, False]}[args.learnings]
    runs: dict[str, list[CampaignRate]] = {}
    with _client(args.api_url, owner_token) as api, _client(args.api_url, approver_token) as boss:
        for learnings_on in modes:
            label = LABEL_ON if learnings_on else LABEL_OFF
            runs[label] = run_campaigns(
                api,
                boss,
                args.campaigns,
                learnings_on=learnings_on,
                quiet_seconds=args.quiet_seconds,
            )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    table = render_table(runs)
    (args.out_dir / "trend.svg").write_text(render_chart(runs))
    (args.out_dir / "results.md").write_text(table)
    (args.out_dir / "results.json").write_text(
        json.dumps({k: [asdict(r) for r in v] for k, v in runs.items()}, indent=2) + "\n"
    )
    sys.stdout.write(table)
    return 0
