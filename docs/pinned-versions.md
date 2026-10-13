# Pinned versions (S0 spike, 2026-10-09)

Pin one alpha after the spike. Upgrade only on purpose (SPEC.md risk 8).
These are the versions that answered over A2A on k3d.

| Part | Version | Digest |
|---|---|---|
| k3s image | `rancher/k3s:v1.37.1-k3s1` (Kubernetes v1.37.1+k3s1) | index `sha256:ca7f37d993d82ef0dcdcfecb2e0e2618ea541dbaffc620c8cedebe01a82acd0d` |
| k3d | v5.9.0 (its default k3s is v1.35.5, so the cluster config sets the image) | n/a |
| Docker Desktop VM | 8 CPUs, 23.4 GiB, kernel 7.0.12-linuxkit arm64 (untouched) | n/a |
| Substrate charts | `substrate-crds` and `substrate` 0.4.0-alpha1 | n/a |
| kubectl-ate | v0.4.0-alpha1 (darwin-arm64) | n/a |
| kagent charts | `kagent-crds` and `kagent` 1.0.0-alpha9 | n/a |
| kagent CLI | 1.0.0-alpha9 (darwin-arm64) | n/a |
| kagent CLI in the Python image | 1.0.0-alpha9 (`kagent-linux-amd64`, `kagent-linux-arm64` from the GitHub release) | amd64 `sha256:fe3d6603b0d549d6814c0c0f07a7e96d4d9f7b3001dfeb8e391bfa5a1195d3cf`, arm64 `sha256:fd880ab9639e066d690d88cf4ef67b7924c7994fcff36033674c2dfe6fe19511` |
| Worker image (`ateom-gvisor`) | v0.4.0-alpha1 | index `sha256:a1ce5b950724c6167889324df6729ccf8c5b3b2963863f4602c21c17587ba454` |
| Harness image (`golang-adk`) | 1.0.0-alpha9 | index `sha256:26ae5c772d4a59b24ecb3619c3499e106e3b28abbc239de25b4ff8d746f97e69` (arm64 manifest `sha256:7bdb821f5495aa4f83aa668a0f5ca629c8555ec656928e694f6a4dac1460e1bf`) |
| Python BYO image (`kagent-adk`) | 1.0.0-alpha9 | `sha256:f60b442fc9f729a7441db2b0814105354c118d5b940cc55bce3ac8c9c1f02f28` |
| Sandbox guest image (`sandbox-guest`) | 1.0.0-alpha9 | `sha256:d5ac5bfa263a0bfa0953804ba9cfec4d9c13b6c78c0af7d36f6e5952630987a2` |
| Standalone sandbox test image (alpine) | 3.20 | `sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` |
| Mock model server (python alpine) | 3.12-alpine, tag only, spike use | `sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4` |
| Dex (OIDC login, test harness and local stack) | `ghcr.io/dexidp/dex:v2.46.0` | `sha256:933fcd3f523338c847b88ef84a7145fb2fcb7b9917f08418612afeaaa2001777` |
| In-cluster check image (`curl`, proof of the Dex issuer from a pod) | `curlimages/curl:8.16.0` | index `sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6` |
| Substrate control images | v0.4.0-alpha1 | ateapi `sha256:0758fdb0...`, atecontroller `sha256:0a5345fa...`, atelet `sha256:386704f0...`, atenet `sha256:01d3b919...`, podcertcontroller `sha256:f8bc68d8...` |
| kagent controller image | 1.0.0-alpha9 | `sha256:3cb8aae886570898c2e70a5e15d67d2498556d3132df3750df39223b206390be` |

## Why not the newest alpha

`docs/sources.md` points at kagent `v1.0.0-alpha11` and Substrate
`0.5.0-alpha2`. The published install guide still names alpha9 and 0.4.0-alpha1.
0.5.0-alpha2 split the certificate controller (`substrate-podcert` chart) and
PostgreSQL out of the main chart, which the guide does not cover. Installing it
with the guide left every Substrate pod stuck in `ContainerCreating` (see
`docs/spike-log.md`). The guide-matching pair works, so it is pinned. Moving to
alpha11 is a separate, deliberate step.

## S1 additions

| Part | Version | Digest |
|---|---|---|
| agentgateway charts | `agentgateway-crds` and `agentgateway` v1.6.0 (`cr.agentgateway.dev/charts`) | n/a |
| agentgateway proxy image (running `agentgateway-proxy` Deployment, read with `--context k3d-ace-spike`) | `cr.agentgateway.dev/agentgateway:v1.6.0` | `sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2ed90c` |

## `make up` additions

`platform/install.sh` fetches `kubectl-ate` v0.4.0-alpha1 from the Substrate GitHub release into
`.bin/` (ignored by git), checks the download against this SHA-256, and ad-hoc signs it on macOS.
The checksums are of the unsigned release files (computed 2026-10-10).

| OS and arch | SHA-256 |
|---|---|
| darwin-amd64 | `031f28ebdc6fdb5a5ccb2dcc4b3873daf6644e0ba42f1ec5e051f11791180ed9` |
| darwin-arm64 | `4e22bd87ed76f5b03f51b5f9fa1393e097ba8d19cbcbb6b568187fc65eed4379` |
| linux-amd64 | `81e60a6dfd9691ff1c41c8ffafb1042db05bfd0a94f8e0ec466a853284956faf` |
| linux-arm64 | `da62dd5137c03e9ede464ddd9cb43ab25577c8f2c3710406a9dbc3731c230cc9` |

## `make dev` and the web image

Tilt is not fetched by any script: install this version on PATH or in `.bin/` (macOS arm64 asset:
`tilt.0.37.8.mac.arm64.tar.gz` from the tilt-dev/tilt release). `platform/dev.sh` refuses any other version.
The base image digests are index digests read with `docker buildx imagetools inspect` on 2026-10-10.

| Part | Version | Digest |
|---|---|---|
| Tilt | v0.37.8 | n/a |
| tilt-extensions (`helm_resource`), `ref` in the Tiltfile | commit `7f9f376076bbe18cb76474d7cdda16894d139b81` (master, 2026-09-12) | n/a |
| Web image build base (`node`) | `node:22-bookworm-slim` | index `sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` |
| Web image runtime base (`nginx-unprivileged`) | `nginxinc/nginx-unprivileged:1.31.5-alpine` | index `sha256:19c132c9ab02d3b783f478743dafc7a7f42e27aa7d2bdcbec1bb1128ca8f2a07` |
| pnpm in the web image build | 9.15.9 (npm package) | n/a |

## The app in the chart

Index digests read with `docker buildx imagetools inspect` on 2026-10-10. The Python image's
dependencies come from `uv.lock` (`uv sync --frozen`).

| Part | Version | Digest |
|---|---|---|
| Python image base (`python`) | `python:3.13-slim-bookworm` | index `sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641` |
| uv in the Python image build | `ghcr.io/astral-sh/uv:0.12.0` | index `sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105` |
| Postgres (chart) | `postgres:16-alpine` | index `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea` |
| Temporal dev server (chart; CLI 1.9.1, Server 1.32.0) | `temporalio/temporal:1.9.1` | index `sha256:ad4c82c97bd12b417d1ea942610dbcd511afb250c4d5ed26c694009533df447e` |

## Image signing (CI publish)

`.github/workflows/publish-images.yml` installs cosign with the installer action pinned by commit
SHA and asks it for this cosign release. The checksums are from the release's
`cosign_checksums.txt` (read 2026-10-10); the local round trip used the darwin-arm64 binary.

| Part | Version | Digest |
|---|---|---|
| cosign | `v3.1.3` | linux-amd64 SHA-256 `4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71`, darwin-arm64 SHA-256 `5cf948c2f4dfe59687bdd0b8523709067383e03982cc543475c8a7dc70e92a76` |
| cosign installer action (`sigstore/cosign-installer`) | v4.1.2 | commit `6f9f17788090df1f26f669e9d70d6ae9567deba6` |

## `make up FULL=1`: traces

Index digests read with `docker buildx imagetools inspect` on 2026-10-11.

| Part | Version | Digest |
|---|---|---|
| OpenTelemetry collector (`otel/opentelemetry-collector-contrib`) | 0.162.0 | `sha256:39923a8e431bd1f57be82411999d389fcfe40857492e4365456d97a4c1f74be6` |
| Grafana, Tempo, Loki, Mimir in one pod (`grafana/otel-lgtm`) | 0.36.0 | index `sha256:57c04cbd8e7022f32bb84c4ac005d79baf8b08e2c5be44facf11f5f1f9944ba2` |
