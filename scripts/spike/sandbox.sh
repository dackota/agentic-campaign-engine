#!/usr/bin/env bash
# S0 live test: create a standalone sandbox, run a command in it, print the output, delete it.
# Exits 0 only when the command's output comes back and the sandbox reaches RUNTIME_STATE_DELETED.
# Needs kubectl-ate/kagent/jq; ACE_BIN defaults to .scratch/bin of the main checkout (untracked).
# Uses the SandboxTemplate spike-sandbox (manifests/spike/sandbox-template.yaml).
set -euo pipefail

COMMON="$(git rev-parse --git-common-dir)"
export PATH="${ACE_BIN:-$(cd "$COMMON/.." && pwd)/.scratch/bin}:$PATH"
KCTX="${KCTX:-k3d-ace-spike}"
NS="${NS:-kagent}"
TEMPLATE="${TEMPLATE:-spike-sandbox}"
LOCAL_PORT="${LOCAL_PORT:-18122}"
MESSAGE="${MESSAGE:-hello from s21 sandbox}"
REQUEST_ID="s21-$(date +%s)-$RANDOM"

fail() { echo "FAIL: $*" >&2; exit 1; }
for tool in kubectl kagent jq; do command -v "$tool" >/dev/null || fail "$tool not on PATH"; done

kubectl --context "$KCTX" port-forward -n "$NS" svc/kagent-controller "$LOCAL_PORT:8083" >/dev/null 2>&1 &
PF=$!
ID=""
cleanup() {
  if [ -n "$ID" ]; then
    ks sandbox delete "$ID" >/dev/null 2>&1 || echo "WARN: sandbox $ID not deleted" >&2
  fi
  kill $PF 2>/dev/null || true
}
trap cleanup EXIT
ks() { kagent --api-url "http://localhost:$LOCAL_PORT" --gateway-url "http://localhost:$LOCAL_PORT" -n "$NS" "$@"; }
for _ in $(seq 1 30); do
  curl -fs "http://localhost:$LOCAL_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

created="$(ks sandbox create "$TEMPLATE" --request-id "$REQUEST_ID" --name "s21-$REQUEST_ID" -o json)" \
  || fail "sandbox create failed"
ID="$(echo "$created" | jq -r .id)"
state="$(echo "$created" | jq -r .state)"
echo "created: $ID $state"
[ "$state" = "RUNTIME_STATE_READY" ] || fail "sandbox not ready: $created"

out="$(ks sandbox exec "$ID" -- sh -c "echo '$MESSAGE'")" || fail "exec failed"
echo "OUTPUT: $out"
[[ "$out" == *"$MESSAGE"* ]] || fail "command output missing"

ks sandbox delete "$ID" >/dev/null || fail "delete failed"
final="$(ks sandbox get "$ID" -o json | jq -r .state)"
echo "after delete: $final"
[ "$final" = "RUNTIME_STATE_DELETED" ] || fail "sandbox not deleted: $final"
ID=""
echo "DELETED"
