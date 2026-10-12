# One trace per campaign

A campaign run is one OpenTelemetry trace, from the click that creates it to the last publish
step, across the API, the worker, the render service, the fakes, and the agents.

## Decision

`POST /campaigns` starts the trace: its request span is the root. The API stores that span's
`traceparent` with the campaign (table `campaign_traces`) and starts the workflow inside it,
so the Temporal tracing interceptor carries the trace into the workflow and every activity.

- A later request for the campaign (approve, retry, a read, a Marketo or Workfront webhook)
  joins the same trace. A middleware outside the OpenTelemetry one finds the campaign (the id in
  the path, or `campaignId` in a webhook body), reads the stored `traceparent`, and puts it on
  the request, so the request's server span is a child of the root.
- The worker's activities call the agent, the fakes, and the render function inside that
  context; httpx instrumentation sends `traceparent` on each call, and the fakes' FastAPI
  instrumentation joins it.
- An agent step is an `invoke_agent` span (gen_ai conventions). kagent and the gateway add the
  model (`chat`) and tool (`execute_tool`) spans under the `traceparent` they receive. The
  scripted agent does the same at fast depth.
- Server and httpx client spans keep the path only: the event stream takes the bearer token in
  its query string.

Rejected: a trace id derived from the campaign UUID. It needs no storage, but the campaign's
trace then has no real root span, and the request spans (`POST /campaigns`, approve, webhook)
sit in traces of their own.

## Consequences

- The trace has a root: the `POST /campaigns` server span (or the caller's client span, when
  the caller is traced too).
- A campaign made before this change has no stored context, and its later requests start
  traces of their own.
- Export is on only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. `make up FULL=1` installs the
  collector and grafana/otel-lgtm, sets it for the app chart (`otel.endpoint`), and turns on
  kagent's `otel.traces` and a gateway tracing policy.
- MCP servers (`services/mcp`) do not exist yet. Each one calls `telemetry.instrument_app`.
