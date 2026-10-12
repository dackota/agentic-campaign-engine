#!/usr/bin/env bash
# S0 live test: an idle agent session suspends, and the next message wakes it with context.
# Sends a message that sets a fact, waits until the session actor is ACTOR_STATE_SUSPENDED,
# sends a second message on the same contextId that asks for the fact, and checks the reply.
# ACE_BIN defaults to .scratch/bin of the main checkout (untracked) and must hold kubectl-ate.
# Exits 0 only when the reply contains the fact. Needs the S0 cluster, kubectl-ate and jq.
set -euo pipefail

COMMON="$(git rev-parse --git-common-dir)"
export PATH="${ACE_BIN:-$(cd "$COMMON/.." && pwd)/.scratch/bin}:$PATH"
KCTX="${KCTX:-k3d-ace-spike}"
NS="${NS:-kagent}"
AGENT="${AGENT:-spike-agent}"
LOCAL_PORT="${LOCAL_PORT:-18121}"
FACT="${FACT:-violet-otter-17}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"
MAX_REPLY_SECONDS="${MAX_REPLY_SECONDS:-180}"
RUN="s21-$(date +%s)"

fail() { echo "FAIL: $*" >&2; exit 1; }
for tool in kubectl kubectl-ate jq curl; do command -v "$tool" >/dev/null || fail "$tool not on PATH"; done

kubectl --context "$KCTX" port-forward -n "$NS" svc/kagent-controller "$LOCAL_PORT:8083" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -fs "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT/.well-known/agent-card.json" >/dev/null 2>&1 && break
  sleep 1
done

send() { # send TEXT [CONTEXT_ID] -> prints the response JSON
  local ctx="${2:-}" body
  body="$(jq -n --arg t "$1" --arg id "$RUN-$RANDOM" --arg c "$ctx" \
    '{jsonrpc:"2.0",id:1,method:"SendMessage",params:{message:({messageId:$id,role:"ROLE_USER",parts:[{text:$t}]}
      + (if $c == "" then {} else {contextId:$c} end))}}')" || return 1
  curl -fsS --max-time "$MAX_REPLY_SECONDS" -H 'content-type: application/json' -H 'A2A-Version: 1.0' -d "$body" \
    "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT"
}
actor_state() {
  kubectl-ate --context "$KCTX" get actors -A | awk -v n="session-$1" '$2 == n {print $4}'
}

# shellcheck disable=SC2310  # checked: jq returns 1 on failure, then curl's status is the function's
first="$(send "The code word is $FACT. Remember it.")" || fail "first message failed"
ctx="$(echo "$first" | jq -r '.result.task.contextId')"
{ [ -n "$ctx" ] && [ "$ctx" != null ]; } || fail "no contextId in: $first"
echo "session: session-$ctx"

state=""
for _ in $(seq 1 "$((WAIT_SECONDS / 2))"); do
  state="$(actor_state "$ctx")"
  [ "$state" = "ACTOR_STATE_SUSPENDED" ] && break
  sleep 2
done
echo "state before second message: ${state:-none}"
[ "$state" = "ACTOR_STATE_SUSPENDED" ] || fail "session did not suspend within ${WAIT_SECONDS}s"

# shellcheck disable=SC2310  # checked: jq returns 1 on failure, then curl's status is the function's
second="$(send "What is the code word?" "$ctx")" || fail "second message failed"
reply="$(echo "$second" | jq -r '[.result.task.artifacts[]?.parts[]?.text // empty] | join("\n")')"
echo "state after second message: $(actor_state "$ctx")"
echo "REPLY: $reply"
[[ "$reply" == *"$FACT"* ]] || fail "reply lost the earlier context"
