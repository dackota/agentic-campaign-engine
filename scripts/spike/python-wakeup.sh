#!/usr/bin/env bash
# S0 (#22): does a Python BYO agent (kagent-adk) survive suspend and wake on Substrate?
# Live depth against the k3d-ace-spike cluster (override with KCTX). Needs kubectl-ate on PATH.
# Phase 1: send a message, print the answer. Phase 2: suspend the session actor, check it is
# suspended, send again on the same contextId, print the answer or the crash.
# Exit 0: phase 1 answered and phase 2 printed its outcome (RESULT: survived or RESULT: crashed;
# a recorded crash is a valid result). Exit 1: the harness failed (setup, phase 1, or the suspend).
set -euo pipefail

KCTX="${KCTX:-k3d-ace-spike}"
NS="${NS:-kagent}"
AGENT="${AGENT:-s22-py-agent}"
HARNESS="${HARNESS:-${AGENT%-agent}-harness}"
LOCAL_PORT="${LOCAL_PORT:-18122}"
CONTROLLER_PORT=8083      # kagent-controller service port
RETRIES="${RETRIES:-120}" # send retries while the actor resumes
SEND_TIMEOUT_S=180        # per-request curl timeout
RETRY_SLEEP_S=1
PF_WAIT_TRIES=30          # port-forward readiness polls
SUSPEND_WAIT_TRIES=60     # actor state polls after suspend
SUSPEND_POLL_S=2
LOG_TAIL_LINES=40
LOG_MATCH_LINES=15
# The server mints the contextId on the first message; the second message reuses it.
# send_message runs in a subshell, so the id travels through a file.
CTX_FILE="$(mktemp)"
CONTEXT_ID=""
PROMPT="${PROMPT:-What is 7 times 6? Answer with just the number.}"

fail() { echo "FAIL: $*" >&2; exit 1; }
k() { kubectl --context "$KCTX" "$@"; }
ate() { kubectl-ate --context "$KCTX" "$@"; }
command -v kubectl-ate >/dev/null || fail "kubectl-ate not on PATH"

# Names of this agent's session actors (template column starts with kagent/<agent>-).
actors() { ate get actors -A | awk -v t="$NS/$AGENT-" 'index($3, t) == 1 {print $2}' | sort; }

send_message() { # prints the answer text; non-zero when the call fails or has no answer
  local body resp
  CONTEXT_ID="$(cat "$CTX_FILE")" || return 1
  body="$(jq -n --arg t "$PROMPT" --arg id "$(uuidgen)" --arg c "$CONTEXT_ID" \
    '{jsonrpc:"2.0",id:1,method:"SendMessage",params:{message:({messageId:$id,role:"ROLE_USER",parts:[{text:$t}]} + (if $c == "" then {} else {contextId:$c} end))}}')" || return 1
  # While the actor resumes, the controller answers KAGENT_SEND_NOT_ACCEPTED with a retry hint.
  for _ in $(seq 1 "$RETRIES"); do
    resp="$(curl -sS --max-time "$SEND_TIMEOUT_S" -H 'content-type: application/json' -H 'A2A-Version: 1.0' -d "$body" \
      "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT")" || { echo "request failed" >&2; return 1; }
    [[ "$resp" == *KAGENT_SEND_NOT_ACCEPTED* ]] || break
    echo "  (session not available yet, retrying)" >&2
    sleep "$RETRY_SLEEP_S"
  done
  { [ -s "$CTX_FILE" ] || echo "$resp" | jq -r '.result.task.contextId // empty' >"$CTX_FILE"; } \
    || { echo "no contextId in response: $resp" >&2; return 1; }
  echo "$resp" | jq -r '[.result.task.artifacts[]?.parts[]?.text // empty] | join("\n")' | grep . \
    || { echo "no answer in response: $resp" >&2; return 1; }
}

# Gate: the Agent is Ready (its golden snapshot is taken) and its Harness is a digest-pinned BYO.
ready="$(k get agent "$AGENT" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
[ "$ready" = "True" ] || fail "agent $AGENT is not Ready (apply manifests/spike/python-byo.yaml)"
image="$(k get harness "$HARNESS" -n "$NS" -o jsonpath='{.spec.workload.image}')"
[[ "$image" == *@sha256:* ]] || fail "harness image is not pinned by digest: $image"
echo "image: $image"

k port-forward -n "$NS" svc/kagent-controller "$LOCAL_PORT:$CONTROLLER_PORT" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true; rm -f "$CTX_FILE"' EXIT
for _ in $(seq 1 "$PF_WAIT_TRIES"); do
  curl -fs "http://localhost:$LOCAL_PORT/agents/$NS/$AGENT/.well-known/agent-card.json" >/dev/null 2>&1 && break
  sleep 1
done

before="$(actors)"
echo "== phase 1: first message"
# shellcheck disable=SC2310  # checked: each step returns 1 on failure
first="$(send_message)" || fail "phase 1: no answer"
echo "$first"
echo "contextId: $(cat "$CTX_FILE")"

actor="$(comm -13 <(echo "$before") <(actors) | head -1)"
[ -n "$actor" ] || fail "could not find the session actor for $AGENT"
echo "actor: $actor"

echo "== suspend"
# shellcheck disable=SC2310  # wrapper: ate is one kubectl-ate call, so its status is kubectl-ate's
out="$(ate suspend actor "$actor" -a "$NS" 2>&1)" || fail "suspend failed: $out"
for _ in $(seq 1 "$SUSPEND_WAIT_TRIES"); do
  state="$(ate get actors -A | awk -v a="$actor" '$2 == a {print $4}')"
  [ "$state" = "ACTOR_STATE_SUSPENDED" ] && break
  sleep "$SUSPEND_POLL_S"
done
echo "state: $state"
[ "$state" = "ACTOR_STATE_SUSPENDED" ] || fail "actor did not reach ACTOR_STATE_SUSPENDED"

echo "== phase 2: second message after wake"
# shellcheck disable=SC2310  # checked: each step returns 1 on failure
if second="$(send_message)"; then
  echo "$second"
  echo "state: $(ate get actors -A | awk -v a="$actor" '$2 == a {print $4}')"
  echo "RESULT: survived"
  exit 0
fi
echo "state: $(ate get actors -A | awk -v a="$actor" '$2 == a {print $4}')"
echo "-- worker log tail"
# shellcheck disable=SC2310  # wrapper: k is one kubectl call, so its status is kubectl's
k logs -n "$NS" -l app.kubernetes.io/name=kagent-default --tail="$LOG_TAIL_LINES" 2>&1 | grep -iE "fatal|illegal|sigill|crash|error" | tail -"$LOG_MATCH_LINES" || true
echo "RESULT: crashed"
exit 0
