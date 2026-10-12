#!/usr/bin/env bash
# S1 live check: agents reach OpenCode Go only through agentgateway.
# Needs the cluster (kube context k3d-ace-spike, override with KCTX) and the output of
# scripts/spike/gateway-install.sh, and OPENCODE_KEY in ENV_FILE (default: .env in the
# main checkout). Exits 0 only when all four checks hold:
#   1. the gateway runs and the ModelConfig points at it with /v1
#   2. the spike agent answers (a2a-smoke.sh) and the gateway log shows tokens per call
#   3. the log shows our user-agent and the x-opencode-session header
#   4. no pod outside agentgateway-system holds a provider key (env, secretKeyRef,
#      mounted Secrets); the gateway's own Secret is the only place OPENCODE_KEY lives.
#      The agent runs as a Substrate sandbox inside a WorkerPool pod, not as its own pod,
#      so the check names the WorkerPool pod it saw and checks the Harness, WorkerPool and
#      SandboxTemplate specs for env and secret refs. The process env inside the sandbox
#      is not visible from the cluster API, and the output says so.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KCTX="${KCTX:-k3d-ace-spike}"
GW_NS="${GW_NS:-agentgateway-system}"
SECRET="${SECRET:-opencode-go-key}"
AGENT_NS="${AGENT_NS:-kagent}"
HARNESS="${HARNESS:-spike-harness}"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"
# kagent's own placeholder Secrets: they hold OPENAI_API_KEY, never a real key. The
# value check below still fails if the OpenCode key ever lands in one of them.
PLACEHOLDER_SECRETS='["kagent-openai","kagent-tools-openai"]'
fail() { echo "FAIL: $*" >&2; exit 1; }
k() { kubectl --context "$KCTX" "$@"; }

[ -f "$ENV_FILE" ] || fail "$ENV_FILE not found; the key value check needs OPENCODE_KEY (set ENV_FILE)"
key="$(sed -n 's/^OPENCODE_KEY=//p' "$ENV_FILE" | head -1)"
[ -n "$key" ] || fail "OPENCODE_KEY is empty in $ENV_FILE; the key value check needs it"

# 1. Gateway and ModelConfig.
# shellcheck disable=SC2310  # wrapper: k is one kubectl call, so its status is kubectl's
k rollout status deploy/agentgateway-proxy -n "$GW_NS" --timeout=60s >/dev/null || fail "gateway proxy not running"
# shellcheck disable=SC2310  # wrapper: k is one kubectl call, so its status is kubectl's
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
# shellcheck disable=SC2310  # wrapper: k is one kubectl call, so its status is kubectl's
line="$(k logs -n "$GW_NS" deploy/agentgateway-proxy --since-time="$since" | grep 'protocol=llm' | tail -1 || true)"
[ -n "$line" ] || fail "no llm request line in gateway log"
in_tok="$(grep -o 'gen_ai.usage.input_tokens=[0-9]*' <<<"$line" | cut -d= -f2 || true)"
out_tok="$(grep -o 'gen_ai.usage.output_tokens=[0-9]*' <<<"$line" | cut -d= -f2 || true)"
{ [ "${in_tok:-0}" -gt 0 ] && [ "${out_tok:-0}" -gt 0 ]; } || fail "no tokens in gateway log: $line"
grep -q 'http.status=200' <<<"$line" || fail "gateway call was not 200: $line"
echo "ok tokens per call: input=$in_tok output=$out_tok"
echo "gateway log: $line"

# 3. Headers OpenCode sees (route sets them; the access log policy prints them).
ua="$(grep -o 'user_agent="[^"]*"' <<<"$line" || true)"
sess="$(grep -o 'opencode_session="[^"]*"' <<<"$line" || true)"
[[ "$ua" == user_agent=\"agentic-campaign-engine/* ]] || fail "user-agent not ours: $ua"
{ [ -n "$sess" ] && [ "$sess" != 'opencode_session="none"' ]; } || fail "no x-opencode-session header: $sess"
echo "ok headers: $ua $sess"

# 4. No agent pod holds a provider key. Pods in $GW_NS are the gateway, not agents.
pool="$(k get harness "$HARNESS" -n "$AGENT_NS" -o jsonpath='{.spec.substrate.workerPoolRef.name}')"
[ -n "$pool" ] || fail "Harness $HARNESS has no substrate.workerPoolRef; agent workload not found"
host="$(k get pods -n "$AGENT_NS" -l "ate.dev/worker-pool=$pool" -o jsonpath='{.items[*].metadata.name}')"
[ -n "$host" ] || fail "no pod for WorkerPool $pool; agent workload not seen"
echo "ok agent workload seen: Harness $HARNESS runs in WorkerPool $pool, pod(s) $host"
# Names of env, envFrom and secret refs only; a value is never printed.
refs="$({ k get harness "$HARNESS" -n "$AGENT_NS" -o json
          k get workerpool "$pool" -n "$AGENT_NS" -o json
          k get sandboxtemplates -n "$AGENT_NS" -o json | jq '.items[]'; } | jq -r '
  . as $o | .spec | paths as $p
  | select(($p[-1] | tostring) | test("^(env|envFrom|secretKeyRef|secretRef|secretName)$"))
  | "\($o.kind)/\($o.metadata.name) .spec.\($p | map(tostring) | join("."))"')"
[ -z "$refs" ] || fail "agent workload specs carry env or secret refs: $refs"
echo "ok no env or secret refs in Harness, WorkerPool $pool or SandboxTemplate specs"
echo "not checked: the process env inside the agent sandbox (not visible from the cluster API)"
pods="$(k get pods -A -o json)"
bad="$(jq -r --arg gw "$GW_NS" --arg s "$SECRET" --argjson ph "$PLACEHOLDER_SECRETS" '
  .items[] | select(.metadata.namespace != $gw) | . as $p
  | ([.spec.containers[], (.spec.initContainers // [])[]] | map(.env // [] | map(
        select(((.name | test("OPENCODE|OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER|GEMINI_API_KEY"))
                and ((.valueFrom.secretKeyRef.name // "") as $n | $ph | index($n) | not))
            or ((.valueFrom.secretKeyRef.name // "") == $s))
        | .name) | .[]) | .[]) as $e
  | "\($p.metadata.namespace)/\($p.metadata.name) env \($e)"' <<<"$pods")"
bad2="$(jq -r --arg s "$SECRET" '
  .items[] | select([.spec.volumes[]? | .secret.secretName, .projected.sources[]?.secret.name] | index($s))
  | "\(.metadata.namespace)/\(.metadata.name) mounts \($s)"' <<<"$pods")"
[ -z "$bad$bad2" ] || fail "provider key reachable from pods: $bad $bad2"
# The key value itself must not appear in any Secret outside the gateway namespace.
b64="$(printf %s "$key" | base64 | tr -d '\n')"
# jq reads the encoded key from its environment, not from its argv.
leaked="$(k get secrets -A -o json | KEY_B64="$b64" jq -r --arg gw "$GW_NS" \
  '.items[] | select(.metadata.namespace != $gw) | select([.data[]?] | index(env.KEY_B64))
   | .metadata.namespace + "/" + .metadata.name')"
[ -z "$leaked" ] || fail "OPENCODE_KEY value found in Secret(s): $leaked"
echo "ok the OpenCode key value is in no Secret outside $GW_NS"
total="$(jq '[.items[] | select(.metadata.namespace != "'"$GW_NS"'")] | length' <<<"$pods")"
echo "ok no provider key in env or mounted Secrets of $total pods outside $GW_NS"
echo "PASS"
