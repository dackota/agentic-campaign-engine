# Decision: k3d, not kind (S0 spike)

Date: 2026-10-09. Status: accepted.

## Decision

Run the demo cluster on k3d with `rancher/k3s:v1.37.1-k3s1`. Do not fall back to
kind.

## Why

- The stack came up on k3d on Apple Silicon (Docker Desktop, 8 CPUs, 23.4 GiB).
  Substrate's gVisor workers run inside the k3d node. `runsc` needs no `/dev/kvm`.
- k3s accepts the runtime config and all three feature gates through k3d
  `extraArgs` (`k3d/ace-spike.yaml`). `certificates.k8s.io/v1beta1` is served and
  pod certificates are issued.
- One k3d-specific fix was needed and took minutes, far inside the one-day time
  box: back `/var/lib/ate` with a Docker volume. Without it Substrate cannot
  mount overlayfs inside the node (overlay refuses an overlayfs upperdir), and
  every actor crashes at start.
- Platform RAM is about 2.3 GiB for the node (all pods, one suspended session).
  See `docs/spike-log.md`.

## Answers to the spike risks

| Risk | Answer |
|---|---|
| 1. gVisor workers inside k3d on arm64 | Yes, with the `/var/lib/ate` volume |
| 2. k3s accepts v1beta1 and the feature gates through k3d args | Yes |
| 3. Python BYO agent survives wake-up | Only with a fast readiness endpoint. See `python-byo-wakeup.md` |
| 8. Alpha churn | Pinned in `docs/pinned-versions.md` |

## S13 (Python BYO agent): see its own decision

The Python wake-up test ran in ticket #22. The decision for S13 is in
`python-byo-wakeup.md`: go, with conditions. It replaces the earlier "no, for now",
which rested on kagent's README alone.

## Fallback

If a later alpha breaks k3d, `kind` v0.32+ with `kindest/node:v1.37.0` and kagent's
`scripts/kind/kind-config.yaml` is the documented path. Nothing in the spike
forced it.
