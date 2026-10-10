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
| Worker image (`ateom-gvisor`) | v0.4.0-alpha1 | index `sha256:a1ce5b950724c6167889324df6729ccf8c5b3b2963863f4602c21c17587ba454` |
| Harness image (`golang-adk`) | 1.0.0-alpha9 | index `sha256:26ae5c772d4a59b24ecb3619c3499e106e3b28abbc239de25b4ff8d746f97e69` (arm64 manifest `sha256:7bdb821f5495aa4f83aa668a0f5ca629c8555ec656928e694f6a4dac1460e1bf`) |
| Sandbox guest image (`sandbox-guest`) | 1.0.0-alpha9 | `sha256:d5ac5bfa263a0bfa0953804ba9cfec4d9c13b6c78c0af7d36f6e5952630987a2` |
| Standalone sandbox test image (alpine) | 3.20 | `sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` |
| Mock model server (python alpine) | 3.12-alpine, tag only, spike use | `sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4` |
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
