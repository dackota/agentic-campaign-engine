# Agentic Campaign Engine

A marketer drops in a threat report. A team of AI agents turns it into a full
campaign. A human approves it. The engine publishes it and learns from the
results.

Runs on Kubernetes (k3d) with [kagent](https://kagent.dev) 1.x and Agent
Substrate.

Status: planning. Read [SPEC.md](SPEC.md) for the plan, the decisions, and the
slices.

## Prerequisites

- Docker Desktop. We recommend 8 CPUs and 16 GiB of memory (a recommendation, not a measured number; see "Docker memory" below).
- [k3d](https://k3d.io), kubectl, helm, jq, and openssl on your `PATH`. Versions are
  pinned in [docs/pinned-versions.md](docs/pinned-versions.md).
- [Tilt](https://tilt.dev), only for `make dev`.
- `kubectl-ate` (the Substrate CLI) needs no install: `make up` fetches it itself,
  checks its pinned checksum, and keeps it in `.bin/`.

## Set up `.env`

Copy `.env.example` to `.env` (git-ignored) and fill in the names it lists. Never
commit a value.

- `OPENCODE_KEY`: required. The key for OpenCode Go.
- `ANTHROPIC_API_KEY`: optional. Left empty, agentgateway's backup route is the
  in-cluster mock.

A key you add later reaches the cluster on the next `make up`.

## Commands

- `make up`: create the `ace` cluster, install the platform, then build, push, and
  install our app.
- `make status`: report the cluster, the platform, and the app: ok or FAIL per check.
- `make dev`: run Tilt on the `ace` cluster, so saving a web file rebuilds and replaces
  the web pod. Run `make up` first.
- `make down`: delete the `ace` cluster, its registry, and its volume.
  `make down` removes only the `ace` cluster; any other cluster stays.

Run `make help` for every target.

## Use the app

- App: http://127.0.0.1:15180/
- Dex (the login): http://dex.ace.localhost:15656/dex

`make up` holds host ports 15180 and 15656. They leave the browser seam's ports
(18080, 15173, 15556) free, so the Playwright tests can run beside the cluster.

Sign in as one of the demo users from `platform/dex/config.yaml`. Demo only: every
user shares the password `demo-password`, and Dex stands in for the company login.

| User | Team | Roles |
|---|---|---|
| dg-owner@demo.example | demand-gen | owner |
| dg-approver@demo.example | demand-gen | approver |
| dg-viewer@demo.example | demand-gen | viewer |
| dg-lead@demo.example | demand-gen | owner, approver |
| pm-owner@demo.example | product-marketing | owner |
| pm-approver@demo.example | product-marketing | approver |
| pm-viewer@demo.example | product-marketing | viewer |

## Docker memory

We recommend giving Docker Desktop 8 CPUs and 16 GiB or more (a recommendation, not a measured number). The numbers come from
[docs/spike-log.md](docs/spike-log.md) section 17 and from a measurement of the cluster:

- Platform pods alone (Substrate, pod certificate controller, kagent): about 900 MiB.
- Platform plus one warm worker plus the k3s system pods: about 1.5 GiB.
- Node total in the spike (`ace-spike`, before our app): 3.44 GiB.
- measured k3d-ace node total: 3.11 GiB. Measured 2026-10-10 on `k3d-ace-server-0`
  with `docker stats --no-stream`, after `make up` finished, with no run in flight.
  Docker Desktop VM 23.4 GiB.

Budget for the pod sums; the node total adds page cache, containerd, and kubelet.
