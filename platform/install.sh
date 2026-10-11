#!/usr/bin/env bash
# Install the platform on the `ace` cluster: Substrate, kagent, agentgateway, Dex, the mock model,
# the S0 agent, and a mock-backed twin of it. Usage: install.sh check-env|run
# The spike scripts do the installing; this script only calls them (always with KCTX set,
# because they default to the other cluster). It never reads .env values: check-env only
# asks whether OPENCODE_KEY has a value, and gateway-install.sh pipes the keys to kubectl.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="k3d-ace"
SPIKE_DIR="${SPIKE_DIR:-$ROOT/scripts/spike}"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"
BIN_DIR="${ATE_BIN_DIR:-$ROOT/.bin}"
ATE_VERSION="v0.4.0-alpha1"
ATE_URL="https://github.com/kagent-dev/substrate/releases/download/$ATE_VERSION"
WORKER_IMAGE="ghcr.io/kagent-dev/substrate/ateom-gvisor@sha256:a1ce5b950724c6167889324df6729ccf8c5b3b2963863f4602c21c17587ba454"
READY_TIMEOUT="${READY_TIMEOUT:-600s}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-120}"
SMOKE_RETRY_DELAY="${SMOKE_RETRY_DELAY:-3}"
TWIN="spike-agent-mock"
AGENT="spike-agent"
# The default workflow's six role Agents (agents/agents.yaml).
ROLE_AGENTS="agent/ace-strategist agent/ace-research agent/ace-email-writer agent/ace-landing-page-writer agent/ace-social-writer agent/ace-one-pager-writer"
HARNESS="spike-harness"
CA_POOLS_ATE="actor-id-jwt-pool actor-id-ca-pool egress-mitm-ca-pool"
CA_POOLS_PODCERT="service-dns-ca-pool pod-identity-ca-pool"

fail() { echo "install: $*" >&2; exit 1; }
k() { kubectl --context "$CTX" "$@"; }

# True when NAME is a whole line of the listing passed as $2 (listings are captured by the
# caller in a plain assignment, so a tool failure stops the script).
has_line() { printf '%s\n' "$2" | grep -qxF -- "$1"; }

# Reject a missing file or an OPENCODE_KEY that is empty once whitespace and quotes are
# stripped. The value is held in a variable only to test it, and is never printed.
check_env() {
  local line value
  [ -f "$ENV_FILE" ] || fail "missing .env file at $ENV_FILE (copy .env.example and fill it in)"
  [ -r "$ENV_FILE" ] || fail "cannot read .env file at $ENV_FILE"
  line="$(grep -m1 '^OPENCODE_KEY=' "$ENV_FILE" || true)"
  value="$(printf '%s' "${line#OPENCODE_KEY=}" | tr -d "[:space:]\"'")"
  [ -n "$value" ] || fail "OPENCODE_KEY is missing or empty in $ENV_FILE"
}

pinned_sha() {
  case "$1" in
    darwin-amd64) echo "031f28ebdc6fdb5a5ccb2dcc4b3873daf6644e0ba42f1ec5e051f11791180ed9" ;;
    darwin-arm64) echo "4e22bd87ed76f5b03f51b5f9fa1393e097ba8d19cbcbb6b568187fc65eed4379" ;;
    linux-amd64) echo "81e60a6dfd9691ff1c41c8ffafb1042db05bfd0a94f8e0ec466a853284956faf" ;;
    linux-arm64) echo "da62dd5137c03e9ede464ddd9cb43ab25577c8f2c3710406a9dbc3731c230cc9" ;;
    *) return 1 ;;
  esac
}

os_arch() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "$arch" in aarch64) arch=arm64 ;; x86_64) arch=amd64 ;; esac
  echo "$os-$arch"
}

fetch_kubectl_ate() {
  local target expected tmp actual
  if [ -x "$BIN_DIR/kubectl-ate" ]; then return 0; fi
  target="$(os_arch)"
  expected="$(pinned_sha "$target")" || fail "no pinned kubectl-ate checksum for $target"
  mkdir -p "$BIN_DIR"
  tmp="$(mktemp "$BIN_DIR/kubectl-ate.XXXXXX")"
  curl -fsSL -o "$tmp" "$ATE_URL/kubectl-ate-$target"
  actual="$(shasum -a 256 "$tmp" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    rm -f "$tmp"
    fail "kubectl-ate checksum mismatch for $target (expected $expected, got $actual)"
  fi
  chmod +x "$tmp"
  # macOS kills a freshly downloaded binary until it carries an ad-hoc signature.
  if [ "$(uname -s)" = Darwin ]; then codesign --force -s - "$tmp"; fi
  mv "$tmp" "$BIN_DIR/kubectl-ate"
}

# Exit 0 when the release and Secret listings ($1 releases, $2 ate-system Secrets, $3
# podcertificate-controller-system Secrets) show Substrate and kagent installed. Pure
# string checks: the caller captures the listings (Secrets by -o name, never data) in plain
# assignments with `|| fail`, so a failing tool stops the script instead of reading as
# "not installed" (set -e is off inside an `if` condition).
platform_installed() {
  local pool release
  for release in substrate kagent; do
    has_line "$release" "$1" || return 1
  done
  for pool in $CA_POOLS_ATE; do has_line "secret/$pool" "$2" || return 1; done
  for pool in $CA_POOLS_PODCERT; do has_line "secret/$pool" "$3" || return 1; done
}

# The smoke can reach a freshly Ready Agent before its session is available; the controller
# answers JSON-RPC -32004 (input not accepted). Retry only that error, until a timeout.
smoke_twin() {
  local deadline=$((SECONDS + SMOKE_TIMEOUT)) out
  while :; do
    if out="$(KCTX="$CTX" AGENT="$TWIN" HARNESS="$HARNESS" "$SPIKE_DIR/a2a-smoke.sh" 2>&1)"; then
      printf '%s\n' "$out"
      return 0
    fi
    if ! printf '%s' "$out" | grep -q -- '-32004'; then
      printf '%s\n' "$out" >&2
      return 1
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      printf '%s\n' "$out" >&2
      fail "A2A smoke: the twin still did not accept input (JSON-RPC -32004, not accepted) after ${SMOKE_TIMEOUT}s"
    fi
    echo "twin not accepting input yet (-32004); retrying in ${SMOKE_RETRY_DELAY}s"
    sleep "$SMOKE_RETRY_DELAY"
  done
}

run() {
  check_env
  fetch_kubectl_ate
  export PATH="$BIN_DIR:$PATH"
  local installed=0 releases ate_secrets podcert_secrets
  releases="$(helm --kube-context "$CTX" list -A --deployed -q)" || fail "could not list Helm releases"
  ate_secrets="$(k get secret -n ate-system -o name)" || fail "could not list Secrets in ate-system"
  podcert_secrets="$(k get secret -n podcertificate-controller-system -o name)" ||
    fail "could not list Secrets in podcertificate-controller-system"
  if platform_installed "$releases" "$ate_secrets" "$podcert_secrets"; then installed=1; fi
  if [ "$installed" = 1 ]; then
    echo "skipping the Substrate and kagent install: both releases and the CA pools are there"
  else
    KCTX="$CTX" WORKER_IMAGE="$WORKER_IMAGE" "$SPIKE_DIR/install.sh"
  fi
  KCTX="$CTX" "$SPIKE_DIR/gateway-install.sh"
  "$ROOT/platform/dex/install.sh" run
  k apply -f "$ROOT/manifests/spike/mock-llm.yaml"
  k apply -f "$ROOT/platform/mock-agent.yaml"
  k apply -f "$ROOT/agents/templates.yaml"
  k apply -f "$ROOT/agents/agents.yaml"
  k wait --for=condition=Ready "agent/$AGENT" "agent/$TWIN" $ROLE_AGENTS -n kagent --timeout="$READY_TIMEOUT"
  smoke_twin
  echo "platform is up; total time ${SECONDS}s"
}

case "${1:-}" in
  check-env) check_env ;;
  run) run ;;
  *) echo "usage: $0 check-env|run" >&2; exit 2 ;;
esac
