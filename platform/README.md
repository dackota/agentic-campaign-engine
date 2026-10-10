# platform

Home for this part. Later tickets fill it.

- `dex/config.yaml`: Dex, the stand-in for the company login. It holds the demo users of
  Demand Gen and Product Marketing with the roles owner, approver, and viewer, and the
  web app's public client (authorization code flow with PKCE). Every demo user's
  password is `demo-password`: demo only. The test harness (`tests/harness/dex.py`)
  starts it in Docker and rewrites the issuer and redirect URIs to its ports.

## The `ace` cluster

- `ace-cluster.yaml`: the k3d config for cluster `ace` (context `k3d-ace`). It copies the first
  cluster's image, runtime config, feature gates, and `/var/lib/ate` volume, adds a registry
  (`k3d-ace-registry`), and maps host ports 15180 (web) and 15656 (Dex) through the load
  balancer to NodePorts 30180 and 30656. Both host ports stay clear of the browser seam's
  18080, 15173, and 15556.
- `cluster.sh up|down|status` backs `make up`, `make down`, `make status`. `preflight.sh` runs
  first on `up`: tools, `.env` present (never read), and at least 6 GiB free Docker memory.
- `make up` is safe to repeat. `make down` removes the `ace` cluster, its registry, and its
  `ace-ate` volume, and nothing else.

## The platform on the cluster

- `install.sh run` (the platform half of `make up`) fetches `kubectl-ate` into `.bin/` (SHA-256
  pinned in `docs/pinned-versions.md`), then calls `scripts/spike/install.sh` (Substrate and
  kagent) and `scripts/spike/gateway-install.sh` (agentgateway and the model key Secrets), always
  with `KCTX=k3d-ace`. The first is skipped on a re-run when both releases and the CA pool
  Secrets exist; the second runs every time. It then applies the mock model and
  `mock-agent.yaml` (a twin of `spike-agent` on the mock model), waits for both Agents, and
  smokes the twin over A2A: no paid model call. `install.sh check-env` stops `make up` first
  when `OPENCODE_KEY` is missing or empty in `.env`; it never prints a value.
- `status.sh` (the platform half of `make status`) prints `ok` or `FAIL` per Helm release,
  controller rollout, and Agent Ready condition.
- `dev.sh` backs `make dev`: it checks the pinned Tilt version, cuts your kubeconfig down to the
  `k3d-ace` context in a temporary file, and runs `tilt up` with it. The `Tiltfile` builds the web
  image and deploys `charts/ace` as release `ace` with `helm_resource`. Run `make up` first.
