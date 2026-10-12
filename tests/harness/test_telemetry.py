"""The shared telemetry module: the traceparent of a span, and an exporter only when asked."""

from ace_engine import telemetry
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

TRACE_ID = 0x0AF7651916CD43DD8448EB211C80319C
SPAN_ID = 0xB7AD6B7169203331


def test_no_traceparent_outside_a_span() -> None:
    assert telemetry.current_traceparent() is None


def test_current_traceparent_names_the_current_span() -> None:
    context = SpanContext(TRACE_ID, SPAN_ID, True, TraceFlags(TraceFlags.SAMPLED))

    with trace.use_span(NonRecordingSpan(context)):
        header = telemetry.current_traceparent()

    assert header == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def test_no_exporter_without_an_endpoint() -> None:
    assert telemetry.exporter_from_environ({}) is None
    assert telemetry.exporter_from_environ({"OTEL_EXPORTER_OTLP_ENDPOINT": "  "}) is None


def test_exporter_from_env_sends_otlp_over_http() -> None:
    exporter = telemetry.exporter_from_environ(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector.observability:4318"}
    )

    assert isinstance(exporter, OTLPSpanExporter)
