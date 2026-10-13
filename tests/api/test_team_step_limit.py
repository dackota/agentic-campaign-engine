"""Seam 1, fast depth: the engine runs at most a set number of each team's steps at once.
A team at its limit waits; another team's steps still run; every run finishes."""

import time
from collections.abc import Callable, Iterator

import pytest

from tests.api.conftest import SignIn
from tests.api.helpers import (
    FINISHED,
    OWNER,
    create_on,
    save_workflow,
    step,
    until_status,
    workflow_name,
)
from tests.harness.scripted_agent import HOLD_MARKER
from tests.harness.stack import Stack

TEAM_STEP_LIMIT = 2
TEAM_A_CAMPAIGNS = 3
OTHER_TEAM_OWNER = "pm-owner@demo.example"
WAIT_SECONDS = 30
POLL_SECONDS = 0.1
# Long enough for a waiting step to have claimed a slot if the limit let it.
SETTLE_SECONDS = 3
TEAM_A_REPORT = f"Team A threat report {HOLD_MARKER}\nActors exploit unpatched VPN appliances."
TEAM_B_REPORT = "Team B threat report\nActors exploit unpatched VPN appliances."


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    """This module's own stack, with a low step limit; `sign_in` signs in against it."""
    with Stack(team_step_limit=TEAM_STEP_LIMIT) as running:
        yield running


def _until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"never saw {what}")


def test_a_team_at_its_step_limit_waits_while_another_team_runs(
    stack: Stack, sign_in: SignIn
) -> None:
    team_a, team_b = sign_in(OWNER), sign_in(OTHER_TEAM_OWNER)
    name = workflow_name("limit")
    save_workflow(team_a, name, {"steps": [step("draft", "agent")], "edges": []})

    team_a_campaigns = [
        create_on(team_a, name, TEAM_A_REPORT)["id"] for _ in range(TEAM_A_CAMPAIGNS)
    ]
    _until(lambda: len(stack.agent.held()) >= TEAM_STEP_LIMIT, "team A at its limit")
    other = create_on(team_b, name, TEAM_B_REPORT)["id"]
    until_status(team_b, other, FINISHED)
    time.sleep(SETTLE_SECONDS)

    running_for_a = len(stack.agent.held())
    stack.agent.release_held()

    assert running_for_a == TEAM_STEP_LIMIT
    for campaign_id in team_a_campaigns:
        assert until_status(team_a, campaign_id, FINISHED)["draft"]
