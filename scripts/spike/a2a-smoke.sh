#!/usr/bin/env bash
# S0 smoke test: one A2A message to the spike Agent must return an answer.
# Live depth: runs against the cluster named ace-spike (kube context k3d-ace-spike,
# override with KCTX). Exits 0 and prints the answer, or exits non-zero.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
NS="${NS:-kagent}"
AGENT="${AGENT:-spike-agent}"
HARNESS="${HARNESS:-spike-harness}"
LOCAL_PORT="${LOCAL_PORT:-18083}"
PROMPT="${PROMPT:-What is 7 times 6? Answer with just the number.}"
EXPECT="${EXPECT:-42}"

fail() { echo "FAIL: $*" >&2; exit 1; }
k() { kubectl --context "$KCTX" "$@"; }

# 1. Written outputs of the spike exist.
for f in docs/spike-log.md docs/pinned-versions.md docs/decisions/k3d-or-kind.md; do
  [ -s "$ROOT/$f" ] || fail "missing or empty $f"
done
ls "$ROOT"/docs/upstream-bugs/*.md >/dev/null 2>&1 || fail "no docs/upstream-bugs/*.md drafts"
for v in k3s k3d Substrate kagent sha256; do
  grep -q "$v" "$ROOT/docs/pinned-versions.md" || fail "pinned-versions.md does not name $v"
done

# 2. The three resources exist and the Harness image is pinned by digest.
k get harness,agenttemplate,agent -n "$NS" >/dev/null || fail "resources not found on $KCTX"
image="$(k get harness "$HARNESS" -n "$NS" -o jsonpath='{.spec.workload.image}')"
[[ "$image" == *@sha256:* ]] || fail "harness image is not pinned by digest: $image"
ready="$(k get agent "$AGENT" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
[ "$ready" = "True" ] || fail "agent $AGENT is not Ready"

# 3. Send one A2A message and read the answer.
k port-forward -n "$NS" svc/kagent-controller "$LOCAL_PORT:8083" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -fs "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT/.well-known/agent-card.json" >/dev/null 2>&1 && break
  sleep 1
done

body="$(jq -n --arg t "$PROMPT" --arg id "$(uuidgen)" \
  '{jsonrpc:"2.0",id:1,method:"SendMessage",params:{message:{messageId:$id,role:"ROLE_USER",parts:[{text:$t}]}}}')"
resp="$(curl -fsS --max-time 180 -H 'content-type: application/json' -H 'A2A-Version: 1.0' -d "$body" \
  "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT")" || fail "A2A request failed"
answer="$(echo "$resp" | jq -r '[.result.task.artifacts[]?.parts[]?.text // empty] | join("\n")')"
[ -n "$answer" ] || fail "no answer in response: $resp"
echo "$answer"
[[ "$answer" == *"$EXPECT"* ]] || fail "answer does not contain $EXPECT"
