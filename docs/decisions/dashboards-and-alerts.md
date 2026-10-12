# Decision: dashboards and alerts as files, shown in the app by a webhook (S12)

Date: 2026-10-11. Status: accepted.

## Decision

- Grafana dashboards (pipeline health, cost, quality, failovers) and alert rules (run
  failure rate, cost spikes, eval score drops, gateway failovers) are files in
  `manifests/observability/grafana`. `make up FULL=1` applies them with kustomize into
  the `lgtm` pod, in the Grafana folder ACE.
- Metrics come from two places. The engine exports run, cost, and eval-score counters
  (`ace_engine/metrics.py`). The collector turns every service's spans into metrics
  (spanmetrics), and the gateway's model-call spans carry the provider that answered.
- The failover rule counts model calls answered by the backup provider. Breaking the
  OpenCode key (a scripted break that points the gateway at a bogus Secret name, never
  reading a key) sends calls to the backup, so the rule fires.
- Grafana's one contact point posts to `POST /alerts/webhook` on the Campaign API with a
  bearer token. The API keeps each alert by fingerprint, lists the firing ones at
  `GET /alerts` for the banner every signed-in user sees, and posts a Slack notice when
  Slack is on (once on firing, once on resolving).
- The token is random, made by `platform/observability.sh`, and kept in Secret
  `alert-webhook` in both namespaces. It never reaches a command line or a log.
- Honeycomb export: when `HONEYCOMB_API_KEY` is set (environment or `.env`), the script
  stores it in Secret `honeycomb` and applies `collector-honeycomb.yaml`, the base
  collector config plus one exporter. With no key the collector sends to Grafana alone.

Test seam exception: the dashboards, alert rules, and Honeycomb overlay are repo files,
so their tests read the files and run `make up` against a stub kubectl. The ticket adds
this repo-files seam to the two in the spec; the alert banner and Slack notice are still
tested through the Campaign API and the browser.

## Why

- Files in the repo review and roll back like code; clicked-together dashboards do not.
- Webhook plus a table keeps the banner independent of Grafana's UI and works at fast
  depth with a fake Slack.
- A second ConfigMap overlay (rather than templating) keeps the no-key path identical to
  before; a test keeps the overlay and the base in step.
