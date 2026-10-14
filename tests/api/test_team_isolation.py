"""Seam 1 at fast depth: team isolation across a real run. Two teams share one Campaign API,
one worker and one Postgres. Row-level security, the 404s for another team's campaign and the
team filter on every view are proved in process on Postgres in tests/engine/test_team_isolation.py;
this keeps the one test that needs two real Dex users and the real worker."""

import uuid

import httpx
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from tests.api.conftest import SignIn
from tests.api.helpers import AWAITING, create_on, until_status

TEAM_A, TEAM_B = "demand-gen", "product-marketing"
TEAM_B_OWNER = "pm-owner@demo.example"


def test_two_teams_run_campaigns_at_once_without_mixing_data(
    api: httpx.Client, sign_in: SignIn
) -> None:
    team_b = sign_in(TEAM_B_OWNER)
    report_a = f"Team A report {uuid.uuid4()}\nActors exploit unpatched VPN appliances."
    report_b = f"Team B report {uuid.uuid4()}\nActors phish payroll staff."

    a = create_on(api, DEFAULT_WORKFLOW_NAME, report_a)
    b = create_on(team_b, DEFAULT_WORKFLOW_NAME, report_b)
    done_a = until_status(api, a["id"], AWAITING)
    done_b = until_status(team_b, b["id"], AWAITING)

    assert (done_a["team"], done_b["team"]) == (TEAM_A, TEAM_B)
    assert (done_a["report"], done_b["report"]) == (report_a, report_b)
    seen_by_a = {c["id"] for c in api.get("/campaigns").json()}
    seen_by_b = {c["id"] for c in team_b.get("/campaigns").json()}
    assert a["id"] in seen_by_a and b["id"] not in seen_by_a
    assert b["id"] in seen_by_b and a["id"] not in seen_by_b
    assert {c["team"] for c in team_b.get("/campaigns").json()} == {TEAM_B}
    steps_a = api.get(f"/campaigns/{a['id']}/steps").json()
    steps_b = team_b.get(f"/campaigns/{b['id']}/steps").json()
    assert steps_a and steps_b
    assert {s["session"] for s in steps_a}.isdisjoint({s["session"] for s in steps_b})
