#!/usr/bin/env bash
# S1: install agentgateway, make the OpenCode Go key Secret from .env, apply the gateway.
# The key is read from OPENCODE_KEY in ENV_FILE (default: .env in the repo root or the
# main checkout) and never printed or written to a file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
AGW_VERSION="${AGW_VERSION:-v1.6.0}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
k() { kubectl --context "$KCTX" "$@"; }

[ -f "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE not found; set ENV_FILE" >&2; exit 1; }
OPENCODE_KEY="$(sed -n 's/^OPENCODE_KEY=//p' "$ENV_FILE" | head -1)"
[ -n "$OPENCODE_KEY" ] || { echo "FAIL: OPENCODE_KEY is empty in $ENV_FILE" >&2; exit 1; }

helm --kube-context "$KCTX" upgrade -i agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --create-namespace -n agentgateway-system --version "$AGW_VERSION"
helm --kube-context "$KCTX" upgrade -i agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  -n agentgateway-system --version "$AGW_VERSION" --wait --timeout 5m

# The gateway reads the key from the Authorization key of the Secret.
k create secret generic opencode-go-key -n agentgateway-system \
  --from-literal=Authorization="$OPENCODE_KEY" --dry-run=client -o yaml | k apply -f - >/dev/null

k apply -f "$ROOT/manifests/spike/gateway.yaml"
k apply -f "$ROOT/manifests/spike/agent.yaml"
