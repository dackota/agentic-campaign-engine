"""The team dashboard: GET /dashboard lists the team's campaigns, oldest first so the list is
the trend, with status, cost, quality score (mean judge score) and click rate (clicks per
open). Everyone in the team reads it; row-level security is the only team filter."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ace_engine import db
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.pg_app import api_over
from tests.support.seed import OTHER_TEAM, TEAM, add_campaign

VIEWER = {"Authorization": "Bearer dg-viewer@demo.example"}
OTHER_TEAM_OWNER = {"Authorization": "Bearer pm-owner@demo.example"}
MICROS_PER_DOLLAR = 1_000_000
OLDEST = datetime(2026, 1, 1, tzinfo=UTC)


def _spend(engine: Engine, campaign_id: uuid.UUID, step: str, micros: int) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            db.StepUsage(
                campaign_id=campaign_id,
                step=step,
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_micros=micros,
            )
        )


def _score(engine: Engine, campaign_id: uuid.UUID, step: str, score: int) -> None:
    reason = json.dumps({"score": score, "reason": "because"})
    with Session(engine) as session, session.begin():
        db.add_event(session, campaign_id, step, db.SCORED, reason)


def _engage(engine: Engine, campaign_id: uuid.UUID, opens: int, clicks: int) -> None:
    with Session(engine) as session, session.begin():
        for kind, count in (("open", opens), ("click", clicks)):
            for _ in range(count):
                session.add(
                    db.Activity(
                        source="marketo",
                        event_id=str(uuid.uuid4()),
                        campaign_id=campaign_id,
                        type=kind,
                        variant="A",
                    )
                )


def _rows(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_each_run_shows_its_status_cost_quality_and_click_rate(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    judged = add_campaign(sqlite_engine, status=db.FINISHED, report="Dash one\nSecond line")
    _spend(sqlite_engine, judged, "landing_page", 1_000_000)
    _spend(sqlite_engine, judged, "social", 250_000)
    _score(sqlite_engine, judged, "landing_page", 4)
    _score(sqlite_engine, judged, "social", 5)
    _engage(sqlite_engine, judged, opens=4, clicks=1)
    unjudged = add_campaign(sqlite_engine, status=db.FAILED, report="Never judged")

    rows = {r["id"]: r for r in _rows(app_client, VIEWER)["campaigns"]}

    assert rows[str(judged)]["status"] == db.FINISHED
    assert rows[str(judged)]["title"] == "Dash one"
    assert rows[str(judged)]["cost_usd"] == pytest.approx(1.25)
    assert rows[str(judged)]["quality_score"] == pytest.approx(4.5)
    assert rows[str(judged)]["click_rate"] == pytest.approx(0.25)
    assert rows[str(unjudged)]["cost_usd"] == 0
    assert rows[str(unjudged)]["quality_score"] is None
    assert rows[str(unjudged)]["click_rate"] is None


def test_campaigns_are_listed_oldest_first_with_the_team_totals(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    # Made out of order, so the order shown is the age, not the order of the rows.
    newest = add_campaign(sqlite_engine, created_at=OLDEST + timedelta(days=2))
    oldest = add_campaign(sqlite_engine, created_at=OLDEST)
    middle = add_campaign(sqlite_engine, created_at=OLDEST + timedelta(days=1))
    _spend(sqlite_engine, oldest, "landing_page", 100_000)
    _spend(sqlite_engine, middle, "landing_page", 300_000)
    _score(sqlite_engine, oldest, "landing_page", 4)
    _score(sqlite_engine, middle, "landing_page", 2)
    _score(sqlite_engine, middle, "social", 2)
    _engage(sqlite_engine, oldest, opens=1, clicks=1)
    _engage(sqlite_engine, middle, opens=3, clicks=0)

    body = _rows(app_client, VIEWER)

    assert [r["id"] for r in body["campaigns"]] == [str(oldest), str(middle), str(newest)]
    assert body["totals"]["runs"] == 3
    assert body["totals"]["cost_usd"] == pytest.approx(0.4)
    # Over every score and every open, not an average of the runs' averages.
    assert body["totals"]["quality_score"] == pytest.approx(8 / 3)
    assert body["totals"]["click_rate"] == pytest.approx(1 / 4)


def test_a_dashboard_with_no_campaigns_has_empty_totals(app_client: TestClient) -> None:
    body = _rows(app_client, VIEWER)

    assert body["campaigns"] == []
    assert body["totals"] == {"runs": 0, "cost_usd": 0, "quality_score": None, "click_rate": None}


def test_another_team_does_not_see_the_dashboard_rows(postgres_engine: Engine) -> None:
    mine = add_campaign(postgres_engine, team=TEAM, report="Private run")
    _spend(postgres_engine, mine, "landing_page", MICROS_PER_DOLLAR)
    _score(postgres_engine, mine, "landing_page", 5)
    _engage(postgres_engine, mine, opens=2, clicks=1)

    theirs = add_campaign(postgres_engine, team=OTHER_TEAM, report="Their run")

    with api_over(postgres_engine) as client:
        own = _rows(client, VIEWER)
        other = _rows(client, OTHER_TEAM_OWNER)

    assert [r["id"] for r in own["campaigns"]] == [str(mine)]
    assert [r["id"] for r in other["campaigns"]] == [str(theirs)]
    assert other["totals"] == {"runs": 1, "cost_usd": 0, "quality_score": None, "click_rate": None}
    assert own["totals"]["runs"] == 1
