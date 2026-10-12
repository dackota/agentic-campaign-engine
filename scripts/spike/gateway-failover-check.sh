#!/usr/bin/env bash
# S1 live check: priority failover and per-team token limits in agentgateway.
# Needs the cluster (kube context k3d-ace-spike, override with KCTX) after
# scripts/spike/gateway-install.sh. Reads no key: the failover test backend carries a
# fixed fake OpenCode key (manifests/spike/gateway-failover-test.yaml). Exits 0 only when:
#   1. a call on the failover-test route, whose priority-1 key is fake, answers 200 from
#      priority group 2 (the mock's Anthropic-style /v1/messages), and the gateway log
#      shows the retry landing on the Anthropic-style provider
#   2. team-a, sent past its token limit, gets a 429, and team-b's call in the same minute
#      gets a 200 from OpenCode Go (team-a's 429 did not evict OpenCode for team-b)
#   3. the gateway log shows tokens per team
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
GW_NS="${GW_NS:-agentgateway-system}"
LOCAL_PORT="${LOCAL_PORT:-18925}"
TEST_MANIFEST="$ROOT/manifests/spike/gateway-failover-test.yaml"
# Each big call is about 8k tokens against a 10k-a-minute team budget.
BIG_REPEATS=4000
MAX_TEAM_A_CALLS=4
BACKEND_ACCEPT_TIMEOUT=60s
# Time for the proxy to pick up the recreated backend and policies.
FAILOVER_SETTLE_S=5
PF_READY_TRIES=30
PF_READY_INTERVAL_S=1
# Time for the access log line to reach the pod log.
LOG_SETTLE_S=2
# Fallback wait when a 429 has no retry-after: one token-limit window (minutes).
DEFAULT_BUDGET_WAIT_S=60
# Slack past retry-after, so the next call lands in the new window.
BUDGET_WAIT_MARGIN_S=1
fail() { echo "FAIL: $*" >&2; exit 1; }
k() { kubectl --context "$KCTX" "$@"; }
# Lines that could carry a key never reach the output.
redact() { grep -v -i -E 'sk-|authorization|api[_-]?key' || true; }

tmp="$(mktemp -d)"
pf=""
cleanup() {
  [ -z "$pf" ] || { kill "$pf" 2>/dev/null || true; wait "$pf" 2>/dev/null || true; }
  rm -rf "$tmp"
}
trap cleanup EXIT

# Fresh test backend: deleting it drops any eviction left from an earlier run, so
# the first call meets the fake key again.
k delete -f "$TEST_MANIFEST" --ignore-not-found >/dev/null
k apply -f "$TEST_MANIFEST" >/dev/null
# shellcheck disable=SC2310  # wrapper: k is one kubectl call, so its status is kubectl's
k wait --for=jsonpath='{.status.conditions[?(@.type=="Accepted")].status}'=True \
  agentgatewaybackend/failover-test -n "$GW_NS" --timeout="$BACKEND_ACCEPT_TIMEOUT" >/dev/null || fail "failover-test backend not accepted"
sleep "$FAILOVER_SETTLE_S"

# kubectl itself, not the k function: $! must be the kubectl process, or cleanup kills
# only a subshell and leaves the port-forward running.
kubectl --context "$KCTX" port-forward -n "$GW_NS" svc/agentgateway-proxy "$LOCAL_PORT:80" >/dev/null 2>&1 &
pf=$!
url="http://127.0.0.1:$LOCAL_PORT"
for _ in $(seq "$PF_READY_TRIES"); do curl -s -o /dev/null "$url/" && break; sleep "$PF_READY_INTERVAL_S"; done
curl -s -o /dev/null "$url/" || fail "port-forward to agentgateway-proxy never answered"
kill -0 "$pf" 2>/dev/null || fail "port-forward exited; is port $LOCAL_PORT taken? set LOCAL_PORT"

post() { # route body_file -> prints the status code; body goes to $tmp/out
  curl -s -o "$tmp/out" -D "$tmp/headers" -w '%{http_code}' "$url/$1/v1/chat/completions" \
    -H content-type:application/json -d @"$2"
}
log_since() { k logs -n "$GW_NS" deploy/agentgateway-proxy --since-time="$1" | { grep 'protocol=llm' || true; } | redact; }

printf '%s' '{"model":"glm-5.3-flash","max_tokens":16,"messages":[{"role":"user","content":"What is 7 times 6?"}]}' >"$tmp/small.json"
filler="$(printf 'filler text %.0s' $(seq "$BIG_REPEATS"))"
printf '{"model":"glm-5.3-flash","max_tokens":5,"messages":[{"role":"user","content":"Reply with ok. %s"}]}' \
  "$filler" >"$tmp/big.json"

# 1. Failover: fake priority-1 key, same call answered by priority group 2.
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code="$(post failover-test "$tmp/small.json")"
[ "$code" = 200 ] || fail "failover call got $code: $(redact <"$tmp/out")"
model="$(jq -r '.model' "$tmp/out")"
answer="$(jq -r '.choices[0].message.content' "$tmp/out")"
[ "$model" = mock-anthropic ] || fail "failover call answered by $model, not priority group 2"
sleep "$LOG_SETTLE_S"
# shellcheck disable=SC2310  # wrapper: one pipeline, so with pipefail its status is the pipeline's
line="$(log_since "$since" | grep 'route=agentgateway-system/failover-test' | tail -1 || true)"
[ -n "$line" ] || fail "no gateway log line for the failover call"
for want in 'endpoint=mock-llm' 'gen_ai.provider.name=anthropic' 'retry.attempt=1' 'http.status=200'; do
  grep -q -- "$want" <<<"$line" || fail "failover log line lacks $want: $line"
done
echo "ok failover: fake OpenCode key, retry answered by the Anthropic-style group 2 ($model: $answer)"
echo "gateway log: $line"

# 2. Team token limits: team-a goes over, team-b still gets through to OpenCode Go.
# A run in the last minute may have spent team-a's budget: wait for its window to reset,
# so this run's team-a calls (and their token counts) land in the log.
# shellcheck disable=SC2310  # wrapper: one curl call, so its status is curl's
if [ "$(post team-a "$tmp/small.json")" = 429 ]; then
  wait_s="$(tr -d '\r' <"$tmp/headers" | awk -F': ' 'tolower($1)=="retry-after" {print $2}' || true)"
  # Retry-After may be an HTTP date; only a number of seconds is used.
  [[ "$wait_s" =~ ^[0-9]+$ ]] || wait_s=""
  echo "team-a budget spent by an earlier run; waiting ${wait_s:-$DEFAULT_BUDGET_WAIT_S}s for its window"
  sleep "$(( ${wait_s:-$DEFAULT_BUDGET_WAIT_S} + BUDGET_WAIT_MARGIN_S ))"
fi
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
calls=0
code=""
while [ "$calls" -lt "$MAX_TEAM_A_CALLS" ]; do
  calls=$((calls + 1))
  code="$(post team-a "$tmp/big.json")"
  [ "$code" = 429 ] && break
  [ "$code" = 200 ] || fail "team-a call $calls got $code: $(redact <"$tmp/out")"
done
[ "$code" = 429 ] || fail "team-a never got a 429 in $MAX_TEAM_A_CALLS calls"
echo "ok team-a 429 on call $calls (over its token limit)"
code="$(post team-b "$tmp/small.json")"
[ "$code" = 200 ] || fail "team-b got $code in the same minute: $(redact <"$tmp/out")"
sleep "$LOG_SETTLE_S"
logs="$(log_since "$since")"
b_line="$(grep 'team="team-b"' <<<"$logs" | tail -1 || true)"
grep -q 'endpoint=opencode.ai' <<<"$b_line" || fail "team-b was not served by OpenCode Go: $b_line"
echo "ok team-b 200 in the same minute, from OpenCode Go"

# 3. Tokens per team in the gateway log, input and output.
team_sum() { # team field -> sum of gen_ai.usage.<field> over that team's log lines
  grep "team=\"$1\"" <<<"$logs" | { grep -o "gen_ai.usage.$2=[0-9]*" || true; } | cut -d= -f2 |
    awk '{s+=$1} END {print s+0}'
}
for team in team-a team-b; do
  # shellcheck disable=SC2310  # wrapper: one pipeline, so with pipefail its status is the pipeline's
  in_sum="$(team_sum "$team" input_tokens || true)"
  # shellcheck disable=SC2310  # wrapper: one pipeline, so with pipefail its status is the pipeline's
  out_sum="$(team_sum "$team" output_tokens || true)"
  { [ "${in_sum:-0}" -gt 0 ] && [ "${out_sum:-0}" -gt 0 ]; } || fail "no tokens logged for $team"
  echo "tokens $team: input=$in_sum output=$out_sum"
done
echo "ok tokens per team in the gateway log"
grep 'team="team-' <<<"$logs" | sed 's/^/gateway log: /'
echo "PASS"
