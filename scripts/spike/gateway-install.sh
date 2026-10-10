#!/usr/bin/env bash
# S1: install agentgateway, make the OpenCode Go key Secret from .env, apply the gateway.
# The key is read from OPENCODE_KEY in ENV_FILE (default: .env in the main checkout, which
# a worktree shares) and never printed, written to a file, or put on a command line.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
AGW_VERSION="${AGW_VERSION:-v1.6.0}"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"
SECRET="${SECRET:-opencode-go-key}"
k() { kubectl --context "$KCTX" "$@"; }

[ -f "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE not found; set ENV_FILE" >&2; exit 1; }
OPENCODE_KEY="$(sed -n 's/^OPENCODE_KEY=//p' "$ENV_FILE" | head -1)"
[ -n "$OPENCODE_KEY" ] || { echo "FAIL: OPENCODE_KEY is empty in $ENV_FILE" >&2; exit 1; }

helm --kube-context "$KCTX" upgrade -i agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --create-namespace -n agentgateway-system --version "$AGW_VERSION"
helm --kube-context "$KCTX" upgrade -i agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
  -n agentgateway-system --version "$AGW_VERSION" --wait --timeout 5m

# The gateway reads the key from the Authorization key of the Secret. printf is a shell
# builtin, so the key reaches kubectl on stdin and never sits in any process's argv.
# Delete and create, not apply: apply would copy the key into the Secret's
# last-applied-configuration annotation. Deleting also drops that annotation from a
# Secret an older version of this script made.
k delete secret "$SECRET" -n agentgateway-system --ignore-not-found >/dev/null
printf %s "$OPENCODE_KEY" | k create secret generic "$SECRET" -n agentgateway-system \
  --from-file=Authorization=/dev/stdin >/dev/null

k apply -f "$ROOT/manifests/spike/gateway.yaml"
k apply -f "$ROOT/manifests/spike/agent.yaml"
