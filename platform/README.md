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
  (`ace-registry`), and maps host ports 15180 (web) and 15656 (Dex) through the load
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
  Secrets exist; the second runs every time. It then applies the mock model,
  `mock-agent.yaml` (a twin of `spike-agent` on the mock model), and the six role Agents of
  `agents/` (AgentTemplates on the gateway model), waits for all of them, and smokes the twin over A2A: no paid model call. `install.sh check-env` stops `make up` first
  when `OPENCODE_KEY` is missing or empty in `.env`; it never prints a value.
- `status.sh` (the platform half of `make status`) prints `ok` or `FAIL` per Helm release,
  controller rollout, and Agent Ready condition.
- `dev.sh` backs `make dev`: it checks the pinned Tilt version, cuts your kubeconfig down to the
  `k3d-ace` context in a temporary file, and runs `tilt up` with it. The `Tiltfile` builds the web
  image and deploys `charts/ace` as release `ace` with `helm_resource`. Run `make up` first.

## The app on the cluster

- `app.sh run` (the last step of `make up`, after the platform) builds the web image (with the
  Dex issuer from `oidc-issuer.txt` as `VITE_OIDC_ISSUER`) and the Python image, pushes both to
  the cluster's local registry (`ace-registry`, on its published local port; nothing goes to
  GHCR), and runs `helm upgrade --install ace charts/ace` with `--wait`. Image tags come from
  the image id, so a changed image rolls its pods. It is the same release `make dev` uses, and
  the chart keeps the app Secret on every upgrade.
- `make status` adds one `app <name>` line for the API, worker, fake Marketo, web, Postgres,
  and Temporal rollouts.

## Dex on the cluster

- `dex/install.sh` (run by `install.sh run`, after agentgateway) installs Dex from plain
  manifests, not a chart, and `charts/` holds nothing about it. `dex/dex.yaml` is namespace
  `dex`, the Deployment (the pinned image), and the Service: a NodePort on port 15656
  (targetPort 5556, nodePort 30656, which `ace-cluster.yaml` maps to host 15656). The config is
  `dex/config.yaml` with three fields rewritten, like `tests/harness/dex.py`: the issuer, the
  web client's redirect URI (`http://127.0.0.1:15180/`), and `web.allowedOrigins`. It goes in as
  the ConfigMap `dex-config`; a changed config restarts the pod.
- `oidc-issuer.txt` is the one place the issuer is written. The Dex step, `status.sh`, and the
  `Tiltfile` (`VITE_OIDC_ISSUER`) read it. The browser reaches it through the k3d load balancer
  (`*.localhost` is 127.0.0.1). Pods reach it through the `coredns-custom` ConfigMap in
  `kube-system` (`dex/coredns-custom.yaml`), which rewrites the host to the Dex Service. The
  step restarts CoreDNS and waits on the rollout so the rewrite is live. A second run is safe.
- `status.sh` adds a Dex line: the discovery document must answer at the issuer and name it.

- `smoke.sh` backs `make smoke`, the platform smoke test: `make up`, then the happy-path
  Campaign API test at live depth (`ACE_DEPTH=live`), which sends one campaign through the
  real kagent email writer and the gateway to the fake Marketo. It spends model tokens.

## Traces (`make up FULL=1`)

- `make up FULL=1` runs `observability.sh` between the platform and the app. It applies
  `manifests/observability/collector.yaml` (namespace `observability`: an OpenTelemetry collector
  on OTLP ports 4317 and 4318, and `grafana/otel-lgtm`), sets kagent's `otel.traces` to the
  collector, and applies a gateway tracing policy. The app chart gets `otel.endpoint`, so the API,
  worker, and fakes export too.
- See Grafana: `kubectl --context k3d-ace -n observability port-forward svc/lgtm 3000:3000`, then
  Explore, Tempo, and the campaign's id as the trace id (hex, no dashes).
- Without `FULL=1` nothing is installed and no service exports.
