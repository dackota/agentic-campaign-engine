"""Seam 1 at fast depth: the team dashboard. GET /dashboard lists the team's campaigns, oldest
first so the list is the trend, with status, cost, quality score (mean judge score) and click
rate (clicks per open). Everyone in the team reads it; row-level security is the only team
filter."""

import json
import uuid
from typing import Any

import httpx
import pytest

from tests.api.conftest import SignIn
from tests.api.helpers import (
    FAILED,
    FINISHED,
    MARKETO_WEBHOOK_PATH,
    REPORT,
    create_on,
    save_workflow,
    signed_headers,
    step,
    until_status,
    workflow_name,
)
from tests.harness.stack import Stack

VIEWER = "dg-viewer@demo.example"
TEAM_B_OWNER = "pm-owner@demo.example"
OPENS, CLICKS = 4, 1


def run_judged(api: httpx.Client, title: str) -> dict[str, Any]:
    name = workflow_name("dash")
    save_workflow(
        api,
        name,
        {
            "steps": [step("landing_page", "agent"), step("judge", "agent")],
            "edges": [{"from": "landing_page", "to": "judge"}],
        },
    )
    created = create_on(api, name, f"{title}\n{REPORT}")
    done = until_status(api, created["id"], FINISHED, FAILED)
    assert done["status"] == FINISHED, done
    return done


def engage(stack: Stack, api: httpx.Client, campaign_id: str) -> None:
    for kind, count in (("open", OPENS), ("click", CLICKS)):
        for _ in range(count):
            body = json.dumps(
                {"id": str(uuid.uuid4()), "type": kind, "campaignId": campaign_id, "variant": "A"}
            ).encode()
            response = api.post(
                MARKETO_WEBHOOK_PATH,
                content=body,
                headers=signed_headers(stack.marketo_webhook_secret, body),
            )
            assert response.status_code < 300, response.text


def rows_of(client: httpx.Client) -> dict[str, dict[str, Any]]:
    response = client.get("/dashboard")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()["campaigns"]}


def test_dashboard_shows_each_run_with_status_cost_quality_and_click_rate(
    stack: Stack, api: httpx.Client
) -> None:
    done = run_judged(api, f"Dash {uuid.uuid4().hex[:8]}")
    engage(stack, api, done["id"])

    row = rows_of(api)[done["id"]]

    assert row["status"] == FINISHED
    assert row["title"].startswith("Dash ")
    assert row["cost_usd"] == pytest.approx(done["cost"]["cost_usd"])
    scores = [s["score"] for s in done["scores"]]
    assert scores
    assert row["quality_score"] == pytest.approx(sum(scores) / len(scores))
    assert row["click_rate"] == pytest.approx(CLICKS / OPENS)


def test_dashboard_lists_campaigns_oldest_first_with_team_totals(
    stack: Stack, api: httpx.Client
) -> None:
    first = run_judged(api, f"Trend {uuid.uuid4().hex[:8]}")
    second = run_judged(api, f"Trend {uuid.uuid4().hex[:8]}")

    body = api.get("/dashboard").json()

    ids = [row["id"] for row in body["campaigns"]]
    assert ids.index(first["id"]) < ids.index(second["id"])
    assert body["totals"]["runs"] == len(ids)
    assert body["totals"]["cost_usd"] == pytest.approx(
        sum(row["cost_usd"] for row in body["campaigns"])
    )


def test_a_viewer_reads_the_dashboard(api: httpx.Client, sign_in: SignIn) -> None:
    done = run_judged(api, f"Viewer {uuid.uuid4().hex[:8]}")

    assert done["id"] in rows_of(sign_in(VIEWER))


def test_another_team_does_not_see_the_dashboard_rows(api: httpx.Client, sign_in: SignIn) -> None:
    done = run_judged(api, f"Private {uuid.uuid4().hex[:8]}")

    assert done["id"] not in rows_of(sign_in(TEAM_B_OWNER))
