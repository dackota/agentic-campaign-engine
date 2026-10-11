"""The shared telemetry module: a campaign's trace id, and an exporter only when asked."""

import uuid

from ace_engine import telemetry
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import get_current_span

TRACE_ID_BITS = 128


def test_campaign_trace_id_is_the_campaign_uuid_as_a_number() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()

    assert (
        telemetry.campaign_trace_id(first) == first.int == telemetry.campaign_trace_id(str(first))
    )
    assert telemetry.campaign_trace_id(first) != telemetry.campaign_trace_id(second)
    assert 0 < telemetry.campaign_trace_id(first) < 2**TRACE_ID_BITS


def test_a_campaign_span_is_current_and_in_the_campaign_trace() -> None:
    campaign_id = uuid.uuid4()

    with telemetry.campaign_span("svc", "work", campaign_id):
        context = get_current_span().get_span_context()

    assert context.trace_id == campaign_id.int


def test_no_exporter_without_an_endpoint() -> None:
    assert telemetry.exporter_from_environ({}) is None
    assert telemetry.exporter_from_environ({"OTEL_EXPORTER_OTLP_ENDPOINT": "  "}) is None


def test_exporter_from_env_sends_otlp_over_http() -> None:
    exporter = telemetry.exporter_from_environ(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector.observability:4318"}
    )

    assert isinstance(exporter, OTLPSpanExporter)
