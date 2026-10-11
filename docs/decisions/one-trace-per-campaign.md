# One trace per campaign

A campaign run is one OpenTelemetry trace, from the click that creates it to the last publish
step, across the API, the worker, the render service, the fakes, and the agents.

## Decision

The trace id is the campaign's UUID (128 bits, the same size). Any service that knows the
campaign id can join its trace with no lookup and no database column:

- The API starts a span in that trace on create, approve, and retry (`telemetry.campaign_span`),
  and the Temporal tracing interceptor carries the trace into the workflow and every activity.
- The worker's activities call the agent, the fakes, and the render function inside that
  context; httpx instrumentation sends `traceparent` on each call, and the fakes' FastAPI
  instrumentation joins it.
- An agent step is an `invoke_agent` span (gen_ai conventions). kagent and the gateway add the
  model (`chat`) and tool (`execute_tool`) spans under the `traceparent` they receive. The
  scripted agent does the same at fast depth.

Rejected: keep the trace id of the first HTTP request in the database. The approval arrives
hours later as a separate request, so it would need a column, a migration, and a read on every
path. A derived id needs none.

## Consequences

- The trace has no exported root span: the root is a remote parent derived from the id.
  Grafana shows the first service span as the top.
- An HTTP server span for a request (for example `POST /campaigns`) is its own trace; the
  `campaign.*` span beside it is in the campaign's trace.
- Export is on only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. `make up FULL=1` installs the
  collector and grafana/otel-lgtm, sets it for the app chart (`otel.endpoint`), and turns on
  kagent's `otel.traces` and a gateway tracing policy.
- MCP servers (`services/mcp`) do not exist yet. Each one calls `telemetry.instrument_app`.
