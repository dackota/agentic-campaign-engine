#!/usr/bin/env bash
# Start Tilt on the `ace` cluster only. Usage: dev.sh
# Tilt gets a kubeconfig cut down to the k3d-ace context, so it cannot reach another
# cluster and your active kubectl context is left alone. Needs `make up` first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
CTX="k3d-ace"
TILT_VERSION="v0.37.8" # keep in step with docs/pinned-versions.md
export PATH="${ACE_BIN_DIR:-$ROOT/.bin}:$PATH"

if ! command -v tilt >/dev/null 2>&1; then
  echo "FAIL tilt is not installed. Install $TILT_VERSION (docs/pinned-versions.md) on PATH or in .bin/" >&2
  exit 1
fi
version="$(tilt version)"
case "$version" in
  "$TILT_VERSION",*|"$TILT_VERSION") ;;
  *)
    echo "FAIL tilt $TILT_VERSION is pinned; found: ${version%%,*}" >&2
    exit 1
    ;;
esac

kubeconfig="$(mktemp)"
trap 'rm -f "$kubeconfig"' EXIT
chmod 600 "$kubeconfig"
if ! kubectl --context "$CTX" config view --minify --flatten >"$kubeconfig"; then
  echo "FAIL could not read context $CTX from your kubeconfig; run make up first" >&2
  exit 1
fi

cd "$ROOT"
KUBECONFIG="$kubeconfig" tilt up
