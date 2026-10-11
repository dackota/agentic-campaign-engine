"""OpenTelemetry for every process we run: one trace per campaign.

A campaign's trace id is its UUID, so any service that knows the campaign id (the API on
create and approve, then everything the workflow calls through Temporal and HTTP headers)
lands in the same trace without a lookup. Spans are exported over OTLP/HTTP when the
standard `OTEL_EXPORTER_OTLP_ENDPOINT` is set (the collector `make up FULL=1` installs);
with it unset nothing is exported and the calls here cost almost nothing.
"""

import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext, TraceFlags
from opentelemetry.trace.propagation import set_span_in_context
from temporalio.contrib.opentelemetry import TracingInterceptor

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
SERVICE_NAME_ENV = "OTEL_SERVICE_NAME"
# Every span we make names its service here: the process's own name for a human reading the
# trace, and the one handle a fast-depth test has when all services share one process.
SERVICE_ATTRIBUTE = "ace.service"
CAMPAIGN_ATTRIBUTE = "ace.campaign_id"
OPERATION_ATTRIBUTE = "gen_ai.operation.name"
SPAN_ID_BITS = 64
_tracer = trace.get_tracer("ace")


def campaign_trace_id(campaign_id: uuid.UUID | str) -> int:
    return uuid.UUID(str(campaign_id)).int


def campaign_context(campaign_id: uuid.UUID | str) -> Context:
    """A context whose current span is the campaign's trace root, so a span started under
    it joins the campaign's trace. The root itself is never exported."""
    trace_id = campaign_trace_id(campaign_id)
    root = SpanContext(
        trace_id=trace_id,
        span_id=(trace_id & (2**SPAN_ID_BITS - 1)) or 1,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(root))


@contextmanager
def campaign_span(service: str, name: str, campaign_id: uuid.UUID | str) -> Iterator[Span]:
    """A span in the campaign's trace, current for the block: calls made inside carry it."""
    with _tracer.start_as_current_span(
        name,
        context=campaign_context(campaign_id),
        attributes={SERVICE_ATTRIBUTE: service, CAMPAIGN_ATTRIBUTE: str(campaign_id)},
    ) as span:
        yield span


@contextmanager
def span(service: str, name: str, operation: str | None = None) -> Iterator[Span]:
    """A child span of the current one. `operation` is the gen_ai operation (invoke_agent,
    chat, execute_tool) for an agent, model, or tool span."""
    attributes = {SERVICE_ATTRIBUTE: service}
    if operation is not None:
        attributes[OPERATION_ATTRIBUTE] = operation
    with _tracer.start_as_current_span(name, attributes=attributes) as made:
        yield made


def exporter_from_environ(environ: Mapping[str, str]) -> SpanExporter | None:
    """An OTLP/HTTP exporter for the endpoint in `environ`, or None when none is set. The
    exporter reads the endpoint, headers, and timeout from the standard variables itself."""
    if not environ.get(ENDPOINT_ENV, "").strip():
        return None
    return OTLPSpanExporter()


def configure(service: str, environ: Mapping[str, str] | None = None) -> None:
    """Export this process's spans to the collector, once. Does nothing when no endpoint is
    set or a tracer provider is already installed (a test's, or an earlier call)."""
    env = os.environ if environ is None else environ
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    exporter = exporter_from_environ(env)
    if exporter is None:
        return
    resource = Resource.create({"service.name": env.get(SERVICE_NAME_ENV, service)})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def instrument_httpx() -> None:
    """Send the current trace's `traceparent` with every httpx request. Safe to repeat."""
    HTTPXClientInstrumentor().instrument()


def instrument_app(app: FastAPI, service: str) -> None:
    """Export a server span per request, joined to the caller's trace by its `traceparent`,
    and propagate the trace on the app's own httpx calls."""
    configure(service)
    instrument_httpx()

    def name_service(span: Span, _scope: object) -> None:
        span.set_attribute(SERVICE_ATTRIBUTE, service)

    FastAPIInstrumentor.instrument_app(app, server_request_hook=name_service)


def temporal_interceptors() -> list[TracingInterceptor]:
    """For a Temporal client: carries the trace into the workflow and its activities."""
    return [TracingInterceptor()]
