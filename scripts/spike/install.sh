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

ate admin make-ca-pool --ca-id=1 --name=service-dns-ca-pool --secret-namespace=podcertificate-controller-system
ate admin make-ca-pool --ca-id=1 --name=pod-identity-ca-pool --secret-namespace=podcertificate-controller-system
ate admin make-jwt-pool --key-id=1 --name=actor-id-jwt-pool --secret-namespace=ate-system
ate admin make-ca-pool --ca-id=1 --name=actor-id-ca-pool --secret-namespace=ate-system
ate admin make-ca-pool --ca-id=1 --name=egress-mitm-ca-pool --secret-namespace=ate-system --key-type=ECDSAP256

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

helm --kube-context "$KCTX" upgrade --install kagent \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$KAGENT_VERSION" -n kagent --timeout 10m \
  -f "$(dirname "$0")/../../manifests/spike/kagent-values.yaml" \
  --set substrateWorkerPool.workerImage="$WORKER_IMAGE"
