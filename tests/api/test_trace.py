"""Seam 1 at fast depth, with an in-memory OpenTelemetry exporter: one campaign run is one
trace across the API, the worker, the render service, the fakes, and the agent."""

import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
from ace_engine import telemetry
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind

from tests.api.helpers import (
    AWAITING,
    MARKETO_WEBHOOK_PATH,
    OWNER,
    SENT,
    create,
    signed_headers,
    until_status,
)
from tests.harness.stack import Stack

# Every service of the run names itself on the spans it makes (`ace.service`).
RUN_SERVICES = {"campaign-api", "campaign-worker", "render", "fake-marketo", "fake-s3", "fake-cms"}
AGENT_OPERATIONS = {"invoke_agent", "chat", "execute_tool"}


def campaign_spans(stack: Stack, campaign_id: str) -> list[ReadableSpan]:
    """The spans of one campaign: the trace whose root is the request span of its
    `POST /campaigns`, which names the campaign."""
    spans = stack.spans.get_finished_spans()
    roots = [
        s
        for s in spans
        if s.attributes
        and s.attributes.get(telemetry.CAMPAIGN_ATTRIBUTE) == campaign_id
        and s.name.startswith("POST /campaigns")
    ]
    assert len(roots) == 1, "the create request's span names the campaign"
    return [s for s in spans if s.context.trace_id == roots[0].context.trace_id]


def services_of(spans: list[ReadableSpan]) -> set[str]:
    return {
        str(s.attributes[telemetry.SERVICE_ATTRIBUTE])
        for s in spans
        if s.attributes and telemetry.SERVICE_ATTRIBUTE in s.attributes
    }


def operations_of(spans: list[ReadableSpan]) -> set[str]:
    return {
        str(s.attributes[telemetry.OPERATION_ATTRIBUTE])
        for s in spans
        if s.attributes and telemetry.OPERATION_ATTRIBUTE in s.attributes
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
    sends = [
        s
        for s in spans
        if s.attributes and s.attributes.get(telemetry.SERVICE_ATTRIBUTE) == "fake-marketo"
    ]
    assert any(s.kind is SpanKind.SERVER for s in sends)


def test_post_campaigns_request_is_the_root_of_one_trace_for_every_request(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    until_status(api, campaign_id, AWAITING)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)
    body = json.dumps(
        {"id": str(uuid.uuid4()), "type": "open", "campaignId": campaign_id, "variant": "A"}
    ).encode()
    hook = api.post(
        MARKETO_WEBHOOK_PATH,
        content=body,
        headers=signed_headers(stack.marketo_webhook_secret, body),
    )
    assert hook.status_code == 202, hook.text

    spans = campaign_spans(stack, campaign_id)

    # One root: the create request (its client span, when the caller is traced too).
    roots = [s for s in spans if s.parent is None]
    assert len(roots) == 1
    assert roots[0].name.startswith("POST")
    servers = {s.name for s in spans if s.kind is SpanKind.SERVER}
    assert {n for n in servers if n.startswith("POST /campaigns/")}, "approve joins the trace"
    assert any(n.startswith("POST /webhooks/marketo") for n in servers)
    assert any(n.startswith("GET /campaigns/") for n in servers)


def test_a_second_campaign_is_a_second_trace(stack: Stack, api: httpx.Client) -> None:
    first, second = create(api)["id"], create(api)["id"]
    until_status(api, first, AWAITING)
    until_status(api, second, AWAITING)

    first_ids = {s.context.trace_id for s in campaign_spans(stack, first)}
    second_ids = {s.context.trace_id for s in campaign_spans(stack, second)}

    assert len(first_ids) == len(second_ids) == 1
    assert first_ids != second_ids


def test_no_span_records_the_access_token_of_the_event_stream(
    stack: Stack, api: httpx.Client
) -> None:
    """The browser sends its bearer token in the event stream's query string, so no span
    attribute may keep a query."""
    campaign_id = create(api)["id"]
    until_status(api, campaign_id, AWAITING)
    token = stack.dex.token(OWNER)

    response = httpx.get(
        f"{stack.api_url}/campaigns/{campaign_id}/events",
        params={"access_token": token},
        timeout=30,
    )

    assert response.status_code == 200
    exported = [
        str(value)
        for s in stack.spans.get_finished_spans()
        for value in (s.attributes or {}).values()
    ]
    assert exported, "the request exported spans"
    leaks = [
        (s.name, key, s.kind)
        for s in stack.spans.get_finished_spans()
        for key, value in (s.attributes or {}).items()
        if token in str(value) or "access_token" in str(value)
    ]
    assert not leaks
