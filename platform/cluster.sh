#!/usr/bin/env bash
# Create, remove, or report the `ace` cluster. Usage: cluster.sh up|down|status
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLUSTER="ace"
CTX="k3d-$CLUSTER"
REGISTRY="$CLUSTER-registry"  # the name in ace-cluster.yaml and app.sh
VOLUME="$CLUSTER-ate"

# True when NAME is the first column of the listing passed as $2. Listings are captured by
# the caller in a plain assignment (or an explicit `if !`), never inside an if condition,
# because bash ignores set -e in a function called from a condition.
has_name() { printf '%s\n' "$2" | awk -v n="$1" '$1 == n { found = 1 } END { exit !found }'; }

first_line() { printf '%s\n' "$1" | head -n 1; }

up() {
  local clusters
  "$HERE/preflight.sh"
  if ! clusters="$(k3d cluster list --no-headers 2>&1)"; then
    echo "FAIL could not list k3d clusters: $(first_line "$clusters")" >&2
    exit 1
  fi
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$CLUSTER" "$clusters"; then
    echo "cluster $CLUSTER already exists; not recreating it"
  else
    k3d cluster create --config "$HERE/ace-cluster.yaml"
  fi
}

down() {
  local clusters registries volumes
  clusters="$(k3d cluster list --no-headers)"
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$CLUSTER" "$clusters"; then k3d cluster delete "$CLUSTER"; fi
  registries="$(k3d registry list --no-headers)"
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$REGISTRY" "$registries"; then k3d registry delete "$REGISTRY"; fi
  registries="$(k3d registry list --no-headers)"
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$REGISTRY" "$registries"; then
    echo "FAIL registry $REGISTRY is still listed after delete" >&2
    exit 1
  fi
  volumes="$(docker volume ls -q)"
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$VOLUME" "$volumes"; then docker volume rm "$VOLUME"; fi
  echo "cluster $CLUSTER, its registry, and its volume are gone"
}

node_ready_states() {
  kubectl --context "$CTX" get nodes -o 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}'
}

kubelet_version() {
  kubectl --context "$CTX" get nodes -o 'jsonpath={.items[0].status.nodeInfo.kubeletVersion}'
}

all_true() { [ -n "$1" ] && ! printf '%s\n' "$1" | tr ' ' '\n' | grep -qvx True; }

status() {
  local failed=0 clusters ready version
  if ! clusters="$(k3d cluster list --no-headers 2>&1)"; then
    echo "FAIL cluster check: k3d failed: $(first_line "$clusters")"
    return 1
  fi
  # shellcheck disable=SC2310  # predicate: is the name in the listing
  if has_name "$CLUSTER" "$clusters"; then
    echo "ok   cluster $CLUSTER exists"
  else
    echo "FAIL cluster $CLUSTER does not exist"
    echo "FAIL node Ready: no cluster"
    echo "FAIL Kubernetes version: no cluster"
    return 1
  fi
  # shellcheck disable=SC2310  # wrapper: one kubectl call, so its status is kubectl's
  if ready="$(node_ready_states 2>&1)"; then
    # shellcheck disable=SC2310  # predicate: is every node Ready
    if all_true "$ready"; then
      echo "ok   node Ready"
    else
      echo "FAIL node Ready (saw: $(first_line "$ready"))"
      failed=1
    fi
  else
    echo "FAIL node Ready (kubectl: $(first_line "$ready"))"
    failed=1
  fi
  # shellcheck disable=SC2310  # wrapper: one kubectl call, so its status is kubectl's
  if version="$(kubelet_version 2>&1)" && [ -n "$version" ]; then
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
