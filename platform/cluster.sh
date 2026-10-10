#!/usr/bin/env bash
# Create, remove, or report the `ace` cluster. Usage: cluster.sh up|down|status
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLUSTER="ace"
CTX="k3d-$CLUSTER"
REGISTRY="k3d-$CLUSTER-registry"
VOLUME="$CLUSTER-ate"

cluster_exists() { k3d cluster get "$CLUSTER" >/dev/null 2>&1; }

up() {
  "$HERE/preflight.sh"
  if cluster_exists; then
    echo "cluster $CLUSTER already exists; not recreating it"
  else
    k3d cluster create --config "$HERE/ace-cluster.yaml"
  fi
}

down() {
  if cluster_exists; then k3d cluster delete "$CLUSTER"; fi
  if k3d registry list 2>/dev/null | grep -q "$REGISTRY"; then k3d registry delete "$REGISTRY"; fi
  if docker volume inspect "$VOLUME" >/dev/null 2>&1; then docker volume rm "$VOLUME"; fi
  echo "cluster $CLUSTER, its registry, and its volume are gone"
}

status() {
  local failed=0 ready version
  if cluster_exists; then
    echo "ok   cluster $CLUSTER exists"
  else
    echo "FAIL cluster $CLUSTER does not exist"
    echo "FAIL node Ready: no cluster"
    echo "FAIL Kubernetes version: no cluster"
    return 1
  fi
  ready="$(kubectl --context "$CTX" get nodes -o 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
  if [ -n "$ready" ] && [ -z "$(printf '%s\n' $ready | grep -vx True)" ]; then
    echo "ok   node Ready"
  else
    echo "FAIL node Ready (saw: ${ready:-none})"
    failed=1
  fi
  version="$(kubectl --context "$CTX" get nodes -o 'jsonpath={.items[0].status.nodeInfo.kubeletVersion}' 2>/dev/null || true)"
  if [ -n "$version" ]; then echo "ok   Kubernetes version $version"; else echo "FAIL Kubernetes version unknown"; failed=1; fi
  return "$failed"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 up|down|status" >&2; exit 2 ;;
esac
