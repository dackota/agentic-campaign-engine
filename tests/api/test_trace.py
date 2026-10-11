"""Seam 1 at fast depth, with an in-memory OpenTelemetry exporter: one campaign run is one
trace across the API, the worker, the render service, the fakes, and the agent."""

import uuid
from collections.abc import Iterator

import httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind

from tests.api.helpers import AWAITING, SENT, create, until_status
from tests.harness.stack import Stack

GEN_AI_OPERATION = "gen_ai.operation.name"
# Every service of the run names itself on the spans it makes (`ace.service`).
RUN_SERVICES = {"campaign-api", "campaign-worker", "render", "fake-marketo", "fake-s3", "fake-cms"}
AGENT_OPERATIONS = {"invoke_agent", "chat", "execute_tool"}


def campaign_spans(stack: Stack, campaign_id: str) -> list[ReadableSpan]:
    """The spans of one campaign: its trace id is the campaign's UUID, as a number."""
    trace_id = uuid.UUID(campaign_id).int
    return [s for s in stack.spans.get_finished_spans() if s.context.trace_id == trace_id]


def services_of(spans: list[ReadableSpan]) -> set[str]:
    return {
        str(s.attributes["ace.service"])
        for s in spans
        if s.attributes and "ace.service" in s.attributes
    }


def operations_of(spans: list[ReadableSpan]) -> set[str]:
    return {
        str(s.attributes[GEN_AI_OPERATION])
        for s in spans
        if s.attributes and GEN_AI_OPERATION in s.attributes
    }


@pytest.fixture
def sent_campaign(stack: Stack, api: httpx.Client, approver: httpx.Client) -> Iterator[str]:
    campaign_id = create(api)["id"]
    until_status(api, campaign_id, AWAITING)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)
    yield campaign_id


def test_one_campaign_run_is_one_trace_with_agent_tool_and_model_spans(
    stack: Stack, sent_campaign: str
) -> None:
    spans = campaign_spans(stack, sent_campaign)

    assert operations_of(spans) >= AGENT_OPERATIONS
    roots = [s for s in spans if s.parent is None or s.parent.is_remote]
    assert roots, "the campaign trace has a first span"


def test_every_service_of_a_run_exports_spans(stack: Stack, sent_campaign: str) -> None:
    spans = campaign_spans(stack, sent_campaign)

    assert services_of(spans) >= RUN_SERVICES


def test_approval_spans_join_the_campaign_trace(stack: Stack, sent_campaign: str) -> None:
    spans = campaign_spans(stack, sent_campaign)
    names = {s.name for s in spans}

    assert "campaign.approve" in names
    assert "campaign.start" in names
    sends = [s for s in spans if s.attributes and s.attributes.get("ace.service") == "fake-marketo"]
    assert any(s.kind is SpanKind.SERVER for s in sends)


def test_a_second_campaign_is_a_second_trace(stack: Stack, api: httpx.Client) -> None:
    first, second = create(api)["id"], create(api)["id"]
    until_status(api, first, AWAITING)
    until_status(api, second, AWAITING)

    first_ids = {s.context.trace_id for s in campaign_spans(stack, first)}
    second_ids = {s.context.trace_id for s in campaign_spans(stack, second)}

    assert len(first_ids) == len(second_ids) == 1
    assert first_ids != second_ids
