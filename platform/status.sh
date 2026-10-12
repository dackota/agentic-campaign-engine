#!/usr/bin/env bash
# Report each platform part of the `ace` cluster: ok or FAIL per Helm release, controller
# rollout, and Agent. Exits non-zero when any line is FAIL. Reads no Secret.
set -euo pipefail
CTX="k3d-ace"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-10s}"
RELEASES="substrate-crds substrate kagent-crds kagent agentgateway-crds agentgateway"
ROLLOUTS="ate-system/ate-controller ate-system/ate-api-server kagent/kagent-controller agentgateway-system/agentgateway-proxy"
APP_NAMESPACE="ace"
APP_DEPLOYMENTS="api worker fake-marketo fake-cms fake-s3 web postgres temporal"
AGENTS="spike-agent spike-agent-mock ace-strategist ace-research ace-email-writer ace-landing-page-writer ace-social-writer ace-one-pager-writer ace-design-agent"
ISSUER_FILE="$(cd "$(dirname "$0")" && pwd)/oidc-issuer.txt"
DEX_TIMEOUT="${DEX_TIMEOUT:-5}"
failed=0

first_line() { printf '%s\n' "$1" | head -n 1; }
k() { kubectl --context "$CTX" "$@"; }
pass() { echo "ok   $*"; }
flunk() { echo "FAIL $*"; failed=1; }

check_releases() {
  local releases release
  if ! releases="$(helm --kube-context "$CTX" list -A --deployed -q 2>&1)"; then
    flunk "helm releases (helm: $(first_line "$releases"))"
    return 0
  fi
  for release in $RELEASES; do
    if printf '%s\n' "$releases" | grep -qxF -- "$release"; then
      pass "release $release deployed"
    else
      flunk "release $release is not deployed"
    fi
  done
}

check_rollouts() {
  local entry out
  for entry in $ROLLOUTS; do
    if out="$(k rollout status "deployment/${entry#*/}" -n "${entry%%/*}" --timeout="$ROLLOUT_TIMEOUT" 2>&1)"; then
      pass "rollout ${entry#*/}"
    else
      flunk "rollout ${entry#*/} (kubectl: $(first_line "$out"))"
    fi
  done
}

check_app() {
  local name out
  for name in $APP_DEPLOYMENTS; do
    if out="$(k rollout status "deployment/$name" -n "$APP_NAMESPACE" --timeout="$ROLLOUT_TIMEOUT" 2>&1)"; then
      pass "app $name"
    else
      flunk "app $name (kubectl: $(first_line "$out"))"
    fi
  done
}

check_agents() {
  local agent ready
  for agent in $AGENTS; do
    if ready="$(k get agent "$agent" -n kagent -o 'jsonpath={.status.conditions[?(@.type=="Ready")].status}' 2>&1)" &&
      [ "$ready" = True ]; then
      pass "agent $agent Ready"
    else
      flunk "agent $agent Ready (saw: $(first_line "$ready"))"
    fi
  done
}

# Dex's discovery document must be reachable at the issuer, and name the same issuer.
check_dex() {
  local issuer body
  issuer="$(tr -d '[:space:]' <"$ISSUER_FILE")" || { flunk "dex (cannot read $ISSUER_FILE)"; return 0; }
  if ! body="$(curl -sS -f --max-time "$DEX_TIMEOUT" "$issuer/.well-known/openid-configuration" 2>&1)"; then
    flunk "dex discovery at $issuer (curl: $(first_line "$body"))"
    return 0
  fi
  if printf '%s' "$body" | tr -d '[:space:]' | grep -qF -- "\"issuer\":\"$issuer\""; then
    pass "dex discovery at $issuer"
  else
    flunk "dex discovery at $issuer names another issuer"
  fi
}

check_releases
check_rollouts
check_agents
check_dex
check_app
exit "$failed"
