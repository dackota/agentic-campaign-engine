"""`make seed-demo`: load the demo data through the Campaign API, so the demo repeats.

Acme Security's two teams, Demand Gen and Product Marketing, each get one finished past
campaign: drafted, approved by the team's approver, and sent. The threat report the video
pastes live is docs/demo-report.txt; it is not seeded, so the on-screen campaign is new.

It is idempotent: a team that already has its campaign (found by the report's first line) is
left as it is, so seeding twice makes no duplicates. It prints one summary per campaign:
team, title, status, step ids, and judge scores, which are the same on every clean stack at
fast depth.

With no --api-url it starts the fast-depth stack, seeds it, and prints the summary: the
check that the seed repeats. With --api-url it seeds that API; --tokens-file is a JSON map
of each demo user's email to a bearer token."""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tests.api.helpers import AWAITING, FINISHED, SENT, create, settle, until_status
from tests.harness.api_client import api_client

SignIn = Callable[[str], httpx.Client]
FINISHED_STATES = (SENT, FINISHED)
# The brand-rendered assets whose bytes are the same on every run (the PDF and deck are not).
TEXT_ASSET_KINDS = ("landing-page", "social", "cards", "graphic")


@dataclass(frozen=True)
class DemoTeam:
    team: str
    owner: str
    approver: str
    report: str


DEMO_TEAMS = (
    DemoTeam(
        team="demand-gen",
        owner="dg-owner@demo.example",
        approver="dg-approver@demo.example",
        report=(
            "Acme Security: fake invoice emails steal staff logins\n"
            "Criminals send invoices that look like they come from a supplier. The link opens "
            "a copy of the staff sign-in page. Staff who type their password hand it over.\n"
            "Turn on a second sign-in step for everyone and report odd invoices to the "
            "security desk."
        ),
    ),
    DemoTeam(
        team="product-marketing",
        owner="pm-owner@demo.example",
        approver="pm-approver@demo.example",
        report=(
            "Acme Security: stolen laptops expose unlocked files\n"
            "Lost and stolen laptops carry customer files in plain form. Anyone who powers "
            "one on can read them.\n"
            "Encrypt every laptop disk and wipe a lost laptop from afar."
        ),
    ),
)


def _title(report: str) -> str:
    return report.splitlines()[0]


def _existing(owner: httpx.Client, title: str) -> dict[str, Any] | None:
    response = owner.get("/campaigns")
    assert response.status_code == 200, response.text
    found = [c for c in response.json() if _title(c["report"]) == title]
    return found[0] if found else None


def _sent(owner: httpx.Client, approver: httpx.Client, team: DemoTeam) -> dict[str, Any]:
    """The team's seeded campaign, created and driven to sent when it is not there yet."""
    campaign = _existing(owner, _title(team.report)) or create(owner, team.report)
    campaign_id: str = campaign["id"]
    if campaign["status"] not in FINISHED_STATES:
        settled = settle(owner, campaign_id)
        if settled["status"] == AWAITING:
            reply = approver.post(f"/campaigns/{campaign_id}/approve")
            assert reply.status_code == 202, reply.text
        campaign = until_status(owner, campaign_id, *FINISHED_STATES)
    else:
        campaign = owner.get(f"/campaigns/{campaign_id}").json()
    return campaign


def _assets(owner: httpx.Client, campaign: dict[str, Any]) -> dict[str, Any]:
    """The email as written, and a hash of each rendered asset: content, no ids or times."""
    previews = {}
    for kind, path in (("email", ""), *((k, f"/{k}") for k in TEXT_ASSET_KINDS)):
        reply = owner.get(f"/campaigns/{campaign['id']}/preview{path}")
        if reply.status_code == httpx.codes.OK:
            previews[kind] = hashlib.sha256(reply.content).hexdigest()
    return {"email": campaign["draft"], "variant_b": campaign["variant_b"], "previews": previews}


def _summary(team: DemoTeam, campaign: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    """What must be the same on every clean stack: no ids, no times."""
    return {
        "team": team.team,
        "title": _title(team.report),
        "status": SENT,
        "steps": [s["id"] for s in campaign["steps"]],
        "scores": {s["step"]: s["score"] for s in campaign["scores"]},
        "assets": assets,
    }


def seed(sign_in: SignIn) -> list[dict[str, Any]]:
    """Load the demo data; `sign_in` gives a Campaign API client for a demo user's email."""
    summaries = []
    for team in DEMO_TEAMS:
        owner = sign_in(team.owner)
        campaign = _sent(owner, sign_in(team.approver), team)
        summaries.append(_summary(team, campaign, _assets(owner, campaign)))
    return summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load the demo data through the Campaign API.")
    parser.add_argument("--api-url", help="a running Campaign API; none starts the fast stack")
    parser.add_argument("--tokens-file", type=Path, help="JSON map of demo user email to token")
    return parser


def _print_summary(summaries: list[dict[str, Any]]) -> None:
    print(json.dumps(summaries, indent=2))


def _read_tokens(path: Path) -> dict[str, str]:
    """The tokens file, checked: a JSON object of email to token with every demo user in it.
    A problem names the file or the missing email, never a token."""
    try:
        tokens = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read the tokens file {path}: {type(exc).__name__}") from exc
    if not isinstance(tokens, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in tokens.items()
    ):
        raise SystemExit("the tokens file must be a JSON object of email to token")
    for team in DEMO_TEAMS:
        for email in (team.owner, team.approver):
            if email not in tokens:
                raise SystemExit(f"the tokens file has no token for {email}")
    return tokens


def main(args: list[str]) -> int:
    """The seed CLI: with --api-url seed that API using --tokens-file; with none, seed a
    fast-depth stack and print the summary."""
    options = _parser().parse_args(args)
    if options.api_url:
        if not options.tokens_file:
            raise SystemExit("--tokens-file is required with --api-url")
        tokens = _read_tokens(options.tokens_file)
        _print_summary(seed(lambda email: api_client(options.api_url, tokens[email])))
        return 0
    from tests.harness.stack import Stack

    with Stack() as stack:
        _print_summary(seed(lambda email: api_client(stack.api_url, stack.dex.token(email))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
