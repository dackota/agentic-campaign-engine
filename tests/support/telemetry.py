"""The in-memory OpenTelemetry span exporter and metric reader, importable without a stack.

OpenTelemetry allows one provider per process, so each is installed the first time it is asked
for. `ace_engine.metrics` creates its instruments at import: install the reader before the
first metric is recorded.
"""

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_SPAN_EXPORTER = InMemorySpanExporter()
_METRIC_READER = InMemoryMetricReader()


def install_span_exporter() -> InMemorySpanExporter:
    """The test exporter, set as the process's tracer provider the first time it is asked for."""
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
        trace.set_tracer_provider(provider)
    return _SPAN_EXPORTER


def install_metric_reader() -> InMemoryMetricReader:
    """The test metric reader, set up the first time it is asked for (one meter provider per
    process, like the tracer provider)."""
    if not isinstance(metrics.get_meter_provider(), MeterProvider):
        metrics.set_meter_provider(MeterProvider(metric_readers=[_METRIC_READER]))
    return _METRIC_READER
