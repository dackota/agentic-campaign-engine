#!/usr/bin/env bash
# `make up FULL=1`: install the OpenTelemetry collector and grafana/otel-lgtm on the `ace`
# cluster, then point agentgateway at the collector. Usage: observability.sh run
# Run it after the platform and before the app: the app chart gets the collector's address
# from `make up` (ACE_OTEL_ENDPOINT).
#
# It also provisions the Grafana dashboards and alert rules (manifests/observability/grafana)
# and makes the bearer token Grafana's alert webhook sends to the Campaign API: one random
# token, kept in Secret alert-webhook in both namespaces. And when HONEYCOMB_API_KEY is set
# (in the environment, or in .env) the collector also exports to Honeycomb. Neither value
# is printed or put on a command line: each reaches kubectl through a pipe or file descriptor.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="k3d-ace"
MANIFESTS="$ROOT/manifests/observability"
READY_TIMEOUT="${READY_TIMEOUT:-300s}"
APP_NAMESPACE="ace"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"

k() { kubectl --context "$CTX" "$@"; }

has_secret() { k get secret -n "$1" -o name | grep -qx "secret/$2"; }

# The webhook token is made once. If either copy is missing, both are made again, so the two
# always agree. Delete and create, not apply: apply would copy the token into an annotation.
ensure_alert_token() {
  if has_secret observability alert-webhook && has_secret "$APP_NAMESPACE" alert-webhook; then
    return
  fi
  local token
  token="$(openssl rand -hex 24)"
  k create namespace "$APP_NAMESPACE" --dry-run=client -o yaml | k apply -f - >/dev/null
  for ns in observability "$APP_NAMESPACE"; do
    k delete secret alert-webhook -n "$ns" --ignore-not-found >/dev/null
    k create secret generic alert-webhook -n "$ns" --from-file=token=<(printf %s "$token") >/dev/null
  done
}

# The key from the environment, or from .env; empty when neither has one.
honeycomb_key() {
  local key="${HONEYCOMB_API_KEY:-}"
  if [ -z "$key" ] && [ -r "$ENV_FILE" ]; then
    key="$(sed -n 's/^HONEYCOMB_API_KEY=//p' "$ENV_FILE" | head -1)"
  fi
  printf %s "$key" | tr -d "[:space:]\"'"
}

# Export to Honeycomb only when the key is set; otherwise the collector sends to Grafana alone.
configure_honeycomb() {
  local key had=""
  key="$(honeycomb_key)"
  has_secret observability honeycomb && had=1
  if [ -n "$key" ]; then
    k delete secret honeycomb -n observability --ignore-not-found >/dev/null
    k create secret generic honeycomb -n observability --from-file=api-key=<(printf %s "$key") >/dev/null
    k apply -f "$MANIFESTS/collector-honeycomb.yaml"
    k rollout restart deployment/otel-collector -n observability
    echo "honeycomb export is on"
  elif [ -n "$had" ]; then
    k delete secret honeycomb -n observability --ignore-not-found >/dev/null
    k rollout restart deployment/otel-collector -n observability
  fi
}

run() {
  k apply -f "$MANIFESTS/collector.yaml"
  ensure_alert_token
  k apply -k "$MANIFESTS/grafana"
  configure_honeycomb
  k rollout status deployment/otel-collector -n observability --timeout="$READY_TIMEOUT"
  k rollout status deployment/lgtm -n observability --timeout="$READY_TIMEOUT"
  # kagent exports through the one kagent install (scripts/spike/install.sh), which
  # `make up FULL=1` runs with ACE_OTEL_ENDPOINT set.
  k apply -f "$MANIFESTS/gateway-tracing.yaml"
  echo "observability is up: Grafana is the lgtm Service in namespace observability, port 3000"
  echo "dashboards and alert rules are provisioned in the Grafana folder ACE"
}

case "${1:-}" in
  run) run ;;
  *) echo "usage: $0 run" >&2; exit 2 ;;
esac
