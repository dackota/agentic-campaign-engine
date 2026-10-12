# services/mcp

Home for this part. Later tickets fill it.

## Telemetry

An MCP server over HTTP calls `ace_engine.telemetry.instrument_app(app, "<name>")` when it
builds its app, so its spans join the campaign trace (docs/decisions/one-trace-per-campaign.md).
