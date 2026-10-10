#!/usr/bin/env bash
# Install Dex on the `ace` cluster. Usage: install.sh [run|render]
#   run     apply Dex (namespace dex), its config, and the CoreDNS rewrite, then wait for both.
#   render  print the Dex config this step would apply; touches no cluster.
# The config is platform/dex/config.yaml with three fields rewritten: the issuer (from
# platform/oidc-issuer.txt), the web client's redirect URI, and web.allowedOrigins.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CTX="k3d-ace"
ISSUER_FILE="$ROOT/platform/oidc-issuer.txt"
WEB_ORIGIN="http://127.0.0.1:15180"
WORK="" # the temp dir `run` makes; the EXIT trap removes it
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-180s}"

fail() { echo "dex: $*" >&2; exit 1; }
k() { kubectl --context "$CTX" "$@"; }

read_issuer() {
  local issuer
  [ -r "$ISSUER_FILE" ] || fail "cannot read $ISSUER_FILE"
  issuer="$(tr -d '[:space:]' <"$ISSUER_FILE")"
  # Characters that are safe inside the sed replacement below.
  [[ "$issuer" =~ ^http://[A-Za-z0-9.:/-]+$ ]] || fail "$ISSUER_FILE does not hold an http URL"
  printf '%s' "$issuer"
}

# Replace the one line that matches $1 (a sed address) with $2, and fail unless exactly one did.
rewrite_line() {
  local pattern="$1" replacement="$2" input="$3" count
  count="$(printf '%s\n' "$input" | grep -cE -- "$pattern")" || count=0
  [ "$count" = 1 ] || fail "config.yaml: expected exactly one line matching $pattern, found $count"
  printf '%s\n' "$input" | sed -E "s|$pattern.*|$replacement|"
}

render_config() {
  local issuer config
  issuer="$(read_issuer)"
  config="$(cat "$HERE/config.yaml")" || fail "cannot read $HERE/config.yaml"
  config="$(rewrite_line '^issuer:' "issuer: $issuer" "$config")"
  config="$(rewrite_line '^  allowedOrigins:' "  allowedOrigins: [\"$WEB_ORIGIN\"]" "$config")"
  config="$(rewrite_line '^    redirectURIs:' "    redirectURIs: [\"$WEB_ORIGIN/\"]" "$config")"
  printf '%s\n' "$config"
}

run() {
  local config sha
  config="$(render_config)"
  sha="$(printf '%s\n' "$config" | shasum -a 256 | awk '{print $1}')"
  [ -n "$sha" ] || fail "could not checksum the rendered config"
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/ace-dex.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  {
    sed "s|__CONFIG_SHA256__|$sha|" "$HERE/dex.yaml"
    printf -- '---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: dex-config\n  namespace: dex\ndata:\n  config.yaml: |\n'
    printf '%s\n' "$config" | sed 's/^/    /'
  } >"$WORK/dex-all.yaml"
  k apply -f "$WORK/dex-all.yaml"
  k -n dex rollout status deployment/dex --timeout="$ROLLOUT_TIMEOUT"
  k apply -f "$HERE/coredns-custom.yaml"
  # CoreDNS reads the override at start, so restart it and wait before anything resolves the name.
  k -n kube-system rollout restart deployment/coredns
  k -n kube-system rollout status deployment/coredns --timeout="$ROLLOUT_TIMEOUT"
  echo "dex is up at $(read_issuer)"
}

case "${1:-run}" in
  run) run ;;
  render) render_config ;;
  *) echo "usage: $0 [run|render]" >&2; exit 2 ;;
esac
