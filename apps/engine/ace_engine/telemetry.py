"""OpenTelemetry for every process we run: one trace per campaign.

`POST /campaigns` starts the campaign's trace: its request span is the root, and the
workflow carries that context through Temporal. The API keeps the root's `traceparent` with
the campaign (`db.CampaignTrace`), so a later request for the campaign (approve, a webhook,
a read) joins the same trace. Spans are exported over OTLP/HTTP when the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` is set (the collector `make up FULL=1` installs); with it
unset nothing is exported and the calls here cost almost nothing.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from temporalio.contrib.opentelemetry import TracingInterceptor

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
SERVICE_NAME_ENV = "OTEL_SERVICE_NAME"
# Every span we make names its service here: the process's own name for a human reading the
# trace, and the one handle a fast-depth test has when all services share one process.
SERVICE_ATTRIBUTE = "ace.service"
CAMPAIGN_ATTRIBUTE = "ace.campaign_id"
OPERATION_ATTRIBUTE = "gen_ai.operation.name"
URL_ATTRIBUTES = ("http.url", "url.full", "http.target", "url.path")
QUERY_ATTRIBUTE = "url.query"
TRACEPARENT_HEADER = "traceparent"
_tracer = trace.get_tracer("ace")


@contextmanager
def span(service: str, name: str, operation: str | None = None) -> Iterator[Span]:
    """A child span of the current one. `operation` is the gen_ai operation (invoke_agent,
    chat, execute_tool) for an agent, model, or tool span."""
    attributes = {SERVICE_ATTRIBUTE: service}
    if operation is not None:
        attributes[OPERATION_ATTRIBUTE] = operation
    with _tracer.start_as_current_span(name, attributes=attributes) as made:
        yield made


def current_traceparent() -> str | None:
    """The W3C `traceparent` of the current span, or None outside a valid span. The API
    stores it for a campaign, so later requests for that campaign join its trace."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get(TRACEPARENT_HEADER)


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
    HTTPXClientInstrumentor().instrument(request_hook=lambda span, _request: _drop_query(span))


def _drop_query(span: Span) -> None:
    """Keep the path only on a span's URL attributes. The event stream takes the
    user's bearer token in its query string (`?access_token=`), and a token must never be
    exported, as it is never logged (campaign_api/__main__.py)."""
    attributes = getattr(span, "attributes", None) or {}
    for key in URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str) and "?" in value:
            span.set_attribute(key, value.split("?", 1)[0])
    if QUERY_ATTRIBUTE in attributes:
        span.set_attribute(QUERY_ATTRIBUTE, "")


def instrument_app(app: FastAPI, service: str) -> None:
    """Export a server span per request, joined to the caller's trace by its `traceparent`,
    and propagate the trace on the app's own httpx calls."""
    configure(service)
    instrument_httpx()

    def name_service(span: Span, _scope: object) -> None:
        span.set_attribute(SERVICE_ATTRIBUTE, service)
        _drop_query(span)

    FastAPIInstrumentor.instrument_app(app, server_request_hook=name_service)


def temporal_interceptors() -> list[TracingInterceptor]:
    """For a Temporal client: carries the trace into the workflow and its activities."""
    return [TracingInterceptor()]
