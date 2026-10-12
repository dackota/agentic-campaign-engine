#!/usr/bin/env bash
# S0: install Agent Substrate and kagent 1.x on an existing cluster.
# Versions come from docs/pinned-versions.md. Needs kubectl-ate on PATH.
set -euo pipefail
KCTX="${KCTX:-k3d-ace-spike}"
SUBSTRATE_VERSION="${SUBSTRATE_VERSION:-0.4.0-alpha1}"
KAGENT_VERSION="${KAGENT_VERSION:-1.0.0-alpha9}"
WORKER_IMAGE="${WORKER_IMAGE:?set WORKER_IMAGE to the ateom-gvisor image pinned by digest}"
k() { kubectl --context "$KCTX" "$@"; }
ate() { kubectl-ate --context "$KCTX" "$@"; }

helm --kube-context "$KCTX" upgrade --install substrate-crds \
  oci://ghcr.io/kagent-dev/substrate/helm/substrate-crds \
  --version "$SUBSTRATE_VERSION" -n ate-system --create-namespace

helm --kube-context "$KCTX" upgrade --install substrate \
  oci://ghcr.io/kagent-dev/substrate/helm/substrate \
  --version "$SUBSTRATE_VERSION" -n ate-system \
  -f "$(dirname "$0")/../../manifests/spike/substrate-values.yaml"

# make-ca-pool and make-jwt-pool fail when the pool Secret exists, so a re-run creates only the
# missing pools. The check reads the Secret's name only, never its data.
ensure_pool() { # <ca|jwt> <name> <secret-namespace> [extra args]
  local kind="$1" name="$2" namespace="$3" id_flag="--ca-id=1"
  [ "$kind" = jwt ] && id_flag="--key-id=1"
  shift 3
  if k get secret "$name" -n "$namespace" -o name >/dev/null 2>&1; then
    echo "$name exists, skipping"
  else
    ate admin "make-$kind-pool" "$id_flag" --name="$name" --secret-namespace="$namespace" "$@"
  fi
}

ensure_pool ca service-dns-ca-pool podcertificate-controller-system
ensure_pool ca pod-identity-ca-pool podcertificate-controller-system
ensure_pool jwt actor-id-jwt-pool ate-system
ensure_pool ca actor-id-ca-pool ate-system
ensure_pool ca egress-mitm-ca-pool ate-system --key-type=ECDSAP256

root="$(k get secret actor-id-ca-pool -n ate-system -o jsonpath='{.data.pool}' | base64 --decode \
  | jq -r '.CAs[0].RootCertificateDER' | base64 --decode | openssl x509 -inform der -outform pem)"
k create secret generic actor-id-ca-certs -n ate-system --from-literal=ca.crt="$root" \
  --dry-run=client -o yaml | k apply -f -

issuer="$(k get --raw /.well-known/openid-configuration | jq -r .issuer)"
k create configmap ate-api-authentication -n ate-system \
  --from-literal=authentication.yaml="actorIdentityJWTProvider: kubernetes
jwtProviders:
- name: kubernetes
  issuer: ${issuer}
  audiences: [api.ate-system.svc]
  certificateAuthorityFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  discoveryTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
" --dry-run=client -o yaml | k apply -f -

helm --kube-context "$KCTX" upgrade substrate \
  oci://ghcr.io/kagent-dev/substrate/helm/substrate \
  --version "$SUBSTRATE_VERSION" -n ate-system --reuse-values --wait --timeout 10m

helm --kube-context "$KCTX" upgrade --install kagent-crds \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version "$KAGENT_VERSION" -n kagent --create-namespace --wait

# `make up FULL=1` sets ACE_OTEL_ENDPOINT: kagent's controller and agents export traces to the
# collector (kagent 1.x docs, Observability > Tracing: the shared endpoint is the collector's
# root, and gains /v1/traces on http/protobuf).
otel_args=()
if [ -n "${ACE_OTEL_ENDPOINT:-}" ]; then
  otel_args=(--set otel.traces.enabled=true --set "otel.exporter.otlp.endpoint=$ACE_OTEL_ENDPOINT"
    --set otel.exporter.otlp.protocol=http/protobuf)
fi

helm --kube-context "$KCTX" upgrade --install kagent \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$KAGENT_VERSION" -n kagent --timeout 10m \
  -f "$(dirname "$0")/../../manifests/spike/kagent-values.yaml" \
  --set substrateWorkerPool.workerImage="$WORKER_IMAGE" \
  ${otel_args[@]+"${otel_args[@]}"}
