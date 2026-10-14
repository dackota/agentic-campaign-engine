"""The metrics the alert rules read: a run that fails counts a failed run, a run that ends counts
how it ended, the cost of each step adds to the cost counter, and each brand review records an
eval score (1 for a pass, 0 for a fix). Read from the in-memory reader as the change a call
makes, so what other tests recorded before does not matter."""

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from ace_engine import cost, db
from ace_engine.agent_roles import role_for
from campaign_worker.activities import Activities, ReviewJob
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.engine.agent_replies import task_reply
from tests.support.campaigns import add_campaign
from tests.support.dag import REPORT
from tests.support.settings import unit_settings
from tests.support.telemetry import install_metric_reader

PAGE = {"headline": "H", "subheadline": "S", "body": "B", "call_to_action": "Go"}
PASS = {"verdict": "pass", "issues": []}
FIX = {"verdict": "fix", "issues": [{"check": "banned_claim", "detail": "banned claim"}]}


@pytest.fixture
def reader() -> InMemoryMetricReader:
    return install_metric_reader()


def _points(reader: InMemoryMetricReader, name: str, **attributes: str) -> list[Any]:
    data = reader.get_metrics_data()
    return [
        point
        for resource in (data.resource_metrics if data else [])
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
        if all((point.attributes or {}).get(k) == v for k, v in attributes.items())
    ]


def _total(reader: InMemoryMetricReader, name: str, **attributes: str) -> float:
    """A counter's total, or the sum of a histogram's values, over the matching points."""
    return sum(
        float(getattr(p, "value", None) or getattr(p, "sum", None) or 0)
        for p in _points(reader, name, **attributes)
    )


def _count(reader: InMemoryMetricReader, name: str, **attributes: str) -> int:
    return int(sum(p.count for p in _points(reader, name, **attributes)))


@pytest.fixture
def activities(sqlite_engine: Engine) -> Activities:
    return Activities(unit_settings(), sqlite_engine)


def test_a_failed_run_counts_as_failed_and_records_why(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    before = _total(reader, "ace.runs", outcome="failed")

    activities.mark_failed(str(campaign_id), "writer", "step 'writer' failed: agent unavailable")

    assert _total(reader, "ace.runs", outcome="failed") == before + 1
    with Session(sqlite_engine) as session:
        campaign = session.get_one(db.Campaign, campaign_id)
        assert campaign.status == db.FAILED
        assert campaign.failure_reason == "step 'writer' failed: agent unavailable"
    events = db.events_after(sqlite_engine, campaign_id, 0)
    assert [(e.step, e.status, e.reason) for e in events] == [
        ("writer", db.STEP_FAILED, "step 'writer' failed: agent unavailable"),
        (db.RUN_STEP, db.FAILED, "step 'writer' failed: agent unavailable"),
    ]


def test_a_run_that_ends_without_a_send_counts_as_finished(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    before = _total(reader, "ace.runs", outcome="finished")

    activities.finish_run(str(campaign_id))

    assert _total(reader, "ace.runs", outcome="finished") == before + 1
    with Session(sqlite_engine) as session:
        assert session.get_one(db.Campaign, campaign_id).status == db.FINISHED
    events = db.events_after(sqlite_engine, campaign_id, 0)
    assert [(e.step, e.status) for e in events] == [(db.RUN_STEP, db.FINISHED)]


def test_a_run_that_ends_after_a_send_counts_as_sent(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine, receipt="receipt-1")
    before = _total(reader, "ace.runs", outcome="sent")

    activities.finish_run(str(campaign_id))

    assert _total(reader, "ace.runs", outcome="sent") == before + 1
    with Session(sqlite_engine) as session:
        assert session.get_one(db.Campaign, campaign_id).status == db.SENT


def test_step_cost_adds_to_the_cost_counter_by_model(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    model = f"model-{uuid.uuid4().hex}"
    usage = {"model": model, "input_tokens": 1200, "output_tokens": 300}
    before = _total(reader, "ace.cost.dollars", model=model)

    # Two replies (the A/B emails) at $0.0081 each.
    activities.save_agent_output(
        str(campaign_id),
        "first",
        {
            "output": [{}, {}],
            "session": "s",
            "usage": (cost.usage_from(usage) + cost.usage_from(usage)).as_dict(),
        },
    )

    assert _total(reader, "ace.cost.dollars", model=model) - before == pytest.approx(0.0162)


def test_a_step_that_cost_nothing_adds_nothing_to_the_cost_counter(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = add_campaign(sqlite_engine)
    model = f"model-{uuid.uuid4().hex}"

    activities.save_agent_output(
        str(campaign_id),
        "first",
        {
            "output": [{}, {}],
            "session": "s",
            "usage": {"model": model, "input_tokens": 0, "output_tokens": 0},
        },
    )

    assert _points(reader, "ace.cost.dollars", model=model) == []


def _reviewer_and_writer(
    replies: list[dict[str, Any]],
) -> Callable[[httpx.Request], httpx.Response]:
    queue = iter(replies)

    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=task_reply(next(queue)))

    return answer


def test_each_brand_review_records_an_eval_score(
    reader: InMemoryMetricReader, activities: Activities, sqlite_engine: Engine
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    # The reviewer asks for a fix, the writer fixes it, the reviewer passes the fix.
    agent = _reviewer_and_writer([FIX, PAGE, PASS])
    job = ReviewJob(campaign_id, "landing_page", REPORT, role_for("landing_page"), {}, "demand-gen")
    count_before = _count(reader, "ace.eval.score")
    sum_before = _total(reader, "ace.eval.score")

    async def review() -> None:
        transport = httpx.MockTransport(agent)
        async with httpx.AsyncClient(transport=transport) as client:
            fixed, _, is_flagged = await activities._review_loop(
                client, job, (PAGE, cost.NO_USAGE, ("session-1",)), review_rounds=2
            )
        assert fixed == PAGE
        assert not is_flagged

    asyncio.run(review())

    # One fix (0) and one pass (1).
    assert _count(reader, "ace.eval.score") == count_before + 2
    assert _total(reader, "ace.eval.score") == sum_before + 1.0
