# Draft for kagent-dev/kagent (docs) or kagent-dev/substrate: install guide fails with Substrate 0.5.0-alpha2

**Versions:** Substrate chart 0.5.0-alpha2, kubectl-ate v0.5.0-alpha2, k3s v1.37.1 (k3d v5.9.0, arm64).
The kagent DEVELOPMENT.md at v1.0.0-alpha11 names 0.5.0-alpha2.

**Repro:** run the steps in https://kagent.dev/docs/kagent/1.x/setup/installation/ with
`--version 0.5.0-alpha2`.

**Actual:**
1. `kubectl ate admin make-ca-pool ... --secret-namespace=podcertificate-controller-system`
   fails: `namespaces "podcertificate-controller-system" not found`.
2. After creating the namespace, every `ate-system` pod stays `ContainerCreating`:
   `MountVolume.SetUp failed for volume "podidentity": credential bundle is not issued yet`.
   All `PodCertificateRequest`s stay `Pending`.

**Cause:** 0.5.0-alpha2 no longer deploys the certificate controller or PostgreSQL.
They live in the `substrate-podcert` chart and `hack/install-postgres.sh`, which also
needs `--set postgres.clientCertificates.enabled=true`.

**Expected:** the install guide matches the chart version it names, or states which
version pair it applies to and how to install the extra pieces.
