#!/usr/bin/env bash
# Build our two images, push them to the `ace` cluster's local registry, and install the app
# chart on the cluster: the app half of `make up`. Usage: app.sh run
# Nothing leaves this machine: the push goes to the k3d registry on a local port, never GHCR.
# The release and namespace match the Tiltfile, so `make up` and `make dev` share one release.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="k3d-ace"
RELEASE="ace"
NAMESPACE="ace"
REGISTRY_CONTAINER="ace-registry"
REGISTRY_PORT=5000       # inside the registry container and the cluster
CLUSTER_REGISTRY="$REGISTRY_CONTAINER:$REGISTRY_PORT"  # how the cluster's nodes pull
ROLLOUT_TIMEOUT="${APP_ROLLOUT_TIMEOUT:-600s}"
ISSUER_FILE="$ROOT/platform/oidc-issuer.txt"

fail() { echo "app: $*" >&2; exit 1; }

# The host port the registry container publishes, for example 62546.
host_port() {
  local mapping
  mapping="$(docker port "$REGISTRY_CONTAINER" "$REGISTRY_PORT/tcp")" ||
    fail "cannot find the cluster registry $REGISTRY_CONTAINER (run make up from the start)"
  mapping="$(printf '%s\n' "$mapping" | head -n 1)"
  printf '%s\n' "${mapping##*:}"
}

# build IMAGE DOCKERFILE [docker build args...]: build, then push under a tag taken from the
# image id, so a changed image changes the chart's values and rolls the pods. Prints the tag.
build_and_push() {
  local image="$1" dockerfile="$2" host_registry="$3" id tag
  shift 3
  # Run in a command substitution, where bash 3.2 ignores set -e: every step checks itself.
  docker build -f "$ROOT/$dockerfile" -t "$image:build" "$@" "$ROOT" >&2 || exit 1
  id="$(docker image inspect --format '{{.Id}}' "$image:build")" || exit 1
  id="${id#sha256:}"
  tag="${id:0:12}"
  docker tag "$image:build" "$host_registry/$image:$tag" || exit 1
  docker push "$host_registry/$image:$tag" >&2 || exit 1
  printf '%s\n' "$tag"
}

run() {
  local port issuer web_tag python_tag
  port="$(host_port)" || exit 1
  issuer="$(tr -d '[:space:]' <"$ISSUER_FILE")" || fail "cannot read $ISSUER_FILE"
  [ -n "$issuer" ] || fail "$ISSUER_FILE is empty"
  web_tag="$(build_and_push ace-web apps/web/Dockerfile "localhost:$port" \
    --build-arg "VITE_OIDC_ISSUER=$issuer")" || exit 1
  python_tag="$(build_and_push ace-python apps/python.Dockerfile "localhost:$port")" || exit 1
  helm --kube-context "$CTX" upgrade --install "$RELEASE" "$ROOT/charts/ace" \
    --namespace "$NAMESPACE" --create-namespace \
    --set "web.image.repository=$CLUSTER_REGISTRY/ace-web" --set "web.image.tag=$web_tag" \
    --set "python.image.repository=$CLUSTER_REGISTRY/ace-python" --set "python.image.tag=$python_tag" \
    --wait --timeout "$ROLLOUT_TIMEOUT"
  echo "app is up: release $RELEASE in $NAMESPACE (web $web_tag, python $python_tag)"
}

case "${1:-}" in
  run) run ;;
  *) echo "usage: $0 run" >&2; exit 2 ;;
esac
