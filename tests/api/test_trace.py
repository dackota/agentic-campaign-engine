"""Seam 1 at fast depth, with an in-memory OpenTelemetry exporter: one campaign run is one
trace across the API, the worker, the render service, the fakes, and the agent. Who joins a
campaign's trace and who does not, the root request and the token-free spans are proved in
process: tests/engine/test_campaign_trace.py."""

import time

import httpx
from ace_engine import telemetry
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind

from tests.api.helpers import AWAITING, SENT, create, until_status
from tests.harness.stack import Stack

SPAN_WAIT_SECONDS = 5
SPAN_POLL_SECONDS = 0.05
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


def until_every_service_has_spans(stack: Stack, campaign_id: str) -> list[ReadableSpan]:
    """The campaign's spans once every service of the run has exported one: the last span of
    a request ends a moment after the response."""
    deadline = time.monotonic() + SPAN_WAIT_SECONDS
    while True:
        spans = campaign_spans(stack, campaign_id)
        if services_of(spans) >= RUN_SERVICES or time.monotonic() > deadline:
            return spans
        time.sleep(SPAN_POLL_SECONDS)


def test_one_campaign_run_is_one_trace_with_agent_tool_and_model_spans(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    until_status(api, campaign_id, AWAITING)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)

    spans = until_every_service_has_spans(stack, campaign_id)

    assert operations_of(spans) >= AGENT_OPERATIONS
    assert [s for s in spans if s.parent is None or s.parent.is_remote], (
        "the trace has a first span"
    )
    assert services_of(spans) >= RUN_SERVICES
    names = {s.name for s in spans}
    assert {"campaign.approve", "campaign.start"} <= names
    marketo_servers = [
        s
        for s in spans
        if s.attributes
        and s.attributes.get(telemetry.SERVICE_ATTRIBUTE) == "fake-marketo"
        and s.kind is SpanKind.SERVER
    ]
    assert marketo_servers, "the fake Marketo's server span is in the campaign's trace"
