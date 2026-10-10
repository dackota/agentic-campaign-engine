#!/usr/bin/env bash
# S1 live check: agents reach OpenCode Go only through agentgateway.
# Needs the cluster (kube context k3d-ace-spike, override with KCTX) and the output of
# scripts/spike/gateway-install.sh. Exits 0 only when all four checks hold:
#   1. the gateway runs and the ModelConfig points at it with /v1
#   2. the spike agent answers (a2a-smoke.sh) and the gateway log shows tokens per call
#   3. the log shows our user-agent and the x-opencode-session header
#   4. no pod outside agentgateway-system holds a provider key (env, secretKeyRef,
#      mounted Secrets); the gateway's own Secret is the only place OPENCODE_KEY lives
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
GW_NS="${GW_NS:-agentgateway-system}"
SECRET="${SECRET:-opencode-go-key}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
fail() { echo "FAIL: $*" >&2; exit 1; }
k() { kubectl --context "$KCTX" "$@"; }

# 1. Gateway and ModelConfig.
k rollout status deploy/agentgateway-proxy -n "$GW_NS" --timeout=60s >/dev/null || fail "gateway proxy not running"
k get secret "$SECRET" -n "$GW_NS" >/dev/null || fail "secret $SECRET missing in $GW_NS"
base="$(k get modelconfig gateway-model -n kagent -o jsonpath='{.spec.openAI.baseUrl}')"
[[ "$base" == http://agentgateway-proxy."$GW_NS".svc*/v1 ]] || fail "ModelConfig baseUrl is not the gateway with /v1: $base"
tmpl="$(k get agenttemplate spike-template -n kagent -o jsonpath='{.spec.modelConfig.name}')"
[ "$tmpl" = "gateway-model" ] || fail "spike template uses $tmpl, not gateway-model"
echo "ok gateway runs, ModelConfig baseUrl=$base"

# 2. One question through the spike agent; the gateway log line for it shows tokens.
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$ROOT/scripts/spike/a2a-smoke.sh" >/dev/null || fail "spike agent did not answer"
sleep 2
line="$(k logs -n "$GW_NS" deploy/agentgateway-proxy --since-time="$since" | grep 'protocol=llm' | tail -1)"
[ -n "$line" ] || fail "no llm request line in gateway log"
in_tok="$(grep -o 'gen_ai.usage.input_tokens=[0-9]*' <<<"$line" | cut -d= -f2)"
out_tok="$(grep -o 'gen_ai.usage.output_tokens=[0-9]*' <<<"$line" | cut -d= -f2)"
[ "${in_tok:-0}" -gt 0 ] && [ "${out_tok:-0}" -gt 0 ] || fail "no tokens in gateway log: $line"
grep -q 'http.status=200' <<<"$line" || fail "gateway call was not 200: $line"
echo "ok tokens per call: input=$in_tok output=$out_tok"
echo "gateway log: $line"

# 3. Headers OpenCode sees (route sets them; the access log policy prints them).
ua="$(grep -o 'user_agent="[^"]*"' <<<"$line" || true)"
sess="$(grep -o 'opencode_session="[^"]*"' <<<"$line" || true)"
[[ "$ua" == user_agent=\"agentic-campaign-engine/* ]] || fail "user-agent not ours: $ua"
[ -n "$sess" ] && [ "$sess" != 'opencode_session="none"' ] || fail "no x-opencode-session header: $sess"
echo "ok headers: $ua $sess"

# 4. No agent pod holds a provider key. Pods in $GW_NS are the gateway, not agents.
pods="$(k get pods -A -o json)"
bad="$(jq -r --arg gw "$GW_NS" '
  .items[] | select(.metadata.namespace != $gw) | . as $p
  | ([.spec.containers[], (.spec.initContainers // [])[]] | map(.env // [] | map(
        select((.name | test("OPENCODE|ANTHROPIC_API_KEY|OPENROUTER|GEMINI_API_KEY"))
            or ((.valueFrom.secretKeyRef.name // "") == "'"$SECRET"'"))
        | .name) | .[]) | .[]) as $e
  | "\($p.metadata.namespace)/\($p.metadata.name) env \($e)"' <<<"$pods")"
bad2="$(jq -r --arg s "$SECRET" '
  .items[] | select([.spec.volumes[]? | .secret.secretName, .projected.sources[]?.secret.name] | index($s))
  | "\(.metadata.namespace)/\(.metadata.name) mounts \($s)"' <<<"$pods")"
[ -z "$bad$bad2" ] || fail "provider key reachable from pods: $bad $bad2"
# The key value itself must not appear in any Secret outside the gateway namespace.
if [ -f "$ENV_FILE" ]; then
  key="$(sed -n 's/^OPENCODE_KEY=//p' "$ENV_FILE" | head -1)"
  if [ -n "$key" ]; then
    b64="$(printf %s "$key" | base64 | tr -d '\n')"
    leaked="$(k get secrets -A -o json | jq -r --arg v "$b64" --arg gw "$GW_NS" \
      '.items[] | select(.metadata.namespace != $gw) | select([.data[]?] | index($v)) | .metadata.namespace + "/" + .metadata.name')"
    [ -z "$leaked" ] || fail "OPENCODE_KEY value found in Secret(s): $leaked"
  fi
fi
total="$(jq '[.items[] | select(.metadata.namespace != "'"$GW_NS"'")] | length' <<<"$pods")"
echo "ok no provider key in env or mounted Secrets of $total pods outside $GW_NS"
echo "PASS"
