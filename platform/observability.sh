#!/usr/bin/env bash
# `make up FULL=1`: install the OpenTelemetry collector and grafana/otel-lgtm on the `ace`
# cluster, then point kagent and agentgateway at the collector. Usage: observability.sh run
# Run it after the platform and before the app: the app chart gets the collector's address
# from `make up` (ACE_OTEL_ENDPOINT). No Secret is read or written.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="k3d-ace"
MANIFESTS="$ROOT/manifests/observability"
KAGENT_VERSION="1.0.0-alpha9"
COLLECTOR_ENDPOINT="http://otel-collector.observability.svc.cluster.local:4318"
READY_TIMEOUT="${READY_TIMEOUT:-300s}"

k() { kubectl --context "$CTX" "$@"; }

run() {
  k apply -f "$MANIFESTS/collector.yaml"
  k rollout status deployment/otel-collector -n observability --timeout="$READY_TIMEOUT"
  k rollout status deployment/lgtm -n observability --timeout="$READY_TIMEOUT"
  # kagent: its controller and every agent export OTLP traces to the collector.
  helm --kube-context "$CTX" upgrade kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --version "$KAGENT_VERSION" -n kagent --reuse-values --timeout 10m \
    --set otel.traces.enabled=true \
    --set "otel.exporter.otlp.endpoint=$COLLECTOR_ENDPOINT" \
    --set otel.exporter.otlp.protocol=http/protobuf
  k apply -f "$MANIFESTS/gateway-tracing.yaml"
  echo "observability is up: Grafana is the lgtm Service in namespace observability, port 3000"
}

case "${1:-}" in
  run) run ;;
  *) echo "usage: $0 run" >&2; exit 2 ;;
esac
