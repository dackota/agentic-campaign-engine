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
