#!/usr/bin/env bash
# Create, remove, or report the `ace` cluster. Usage: cluster.sh up|down|status
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLUSTER="ace"
CTX="k3d-$CLUSTER"
REGISTRY="k3d-$CLUSTER-registry"
VOLUME="$CLUSTER-ate"

# True when NAME is the first column of the command's output. Tool errors are not
# swallowed: the captured call runs under set -e, so a failing tool stops the script.
has_name() { printf '%s\n' "$2" | awk -v n="$1" '$1 == n { found = 1 } END { exit !found }'; }

cluster_exists() {
  local list
  list="$(k3d cluster list --no-headers)"
  has_name "$CLUSTER" "$list"
}

up() {
  "$HERE/preflight.sh"
  if cluster_exists; then
    echo "cluster $CLUSTER already exists; not recreating it"
  else
    k3d cluster create --config "$HERE/ace-cluster.yaml"
  fi
}

down() {
  local clusters registries volumes
  clusters="$(k3d cluster list --no-headers)"
  if has_name "$CLUSTER" "$clusters"; then k3d cluster delete "$CLUSTER"; fi
  registries="$(k3d registry list --no-headers)"
  if has_name "$REGISTRY" "$registries"; then k3d registry delete "$REGISTRY"; fi
  volumes="$(docker volume ls -q)"
  if has_name "$VOLUME" "$volumes"; then docker volume rm "$VOLUME"; fi
  echo "cluster $CLUSTER, its registry, and its volume are gone"
}

first_line() { printf '%s\n' "$1" | head -n 1; }

status() {
  local failed=0 clusters ready version
  if ! clusters="$(k3d cluster list --no-headers 2>&1)"; then
    echo "FAIL cluster check: k3d failed: $(first_line "$clusters")"
    return 1
  fi
  if has_name "$CLUSTER" "$clusters"; then
    echo "ok   cluster $CLUSTER exists"
  else
    echo "FAIL cluster $CLUSTER does not exist"
    echo "FAIL node Ready: no cluster"
    echo "FAIL Kubernetes version: no cluster"
    return 1
  fi
  if ready="$(kubectl --context "$CTX" get nodes -o 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}' 2>&1)" &&
    [ -n "$ready" ] && ! printf '%s\n' "$ready" | tr ' ' '\n' | grep -qvx True; then
    echo "ok   node Ready"
  else
    echo "FAIL node Ready (saw: $(first_line "$ready"))"
    failed=1
  fi
  if version="$(kubectl --context "$CTX" get nodes -o 'jsonpath={.items[0].status.nodeInfo.kubeletVersion}' 2>&1)" && [ -n "$version" ]; then
    echo "ok   Kubernetes version $version"
  else
    echo "FAIL Kubernetes version (kubectl: $(first_line "$version"))"
    failed=1
  fi
  return "$failed"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 up|down|status" >&2; exit 2 ;;
esac
