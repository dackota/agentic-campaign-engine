# Sources

These are the pages read during the planning session on 2026-10-09. Each row
says what the page told us. GitHub links point at the tag we read, so they do
not drift. kagent 1.x is alpha and changes every few days, so check the live
page before you rely on a row.

## The role

| Source | What it told us |
|---|---|
| [Job post on Workday](https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/job/USA---Remote/Sr-Full-Stack-Engineer--Remote-_R29072-1) | The title is now "Sr. AI Growth Engineer (Remote)". It is on the marketing team. The "What You'll Do" and "What You'll Need" lists that SPEC.md maps to slices. Applications close 2026-12-02 |
| [Same post, Workday JSON API](https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/job/USA---Remote/Sr-Full-Stack-Engineer--Remote-_R29072-1) | The page is rendered by JavaScript. This endpoint returns the full text |

## Prior work

| Source | What it told us |
|---|---|
| [agent-golden-path](https://github.com/dackota/agent-golden-path) | The kagent 0.10 golden path. Shows Argo CD, LiteLLM, and promptfoo were already covered, so this repo uses other tools |

## kagent 1.x

| Source | What it told us |
|---|---|
| [The future of kagent](https://kagent.dev/blog/the-future-of-kagent) | kagent moves from Deployments to Agent Substrate. Every agent runs in a sandbox. Breaking changes. 0.10.x stays on its own branch |
| [kagent 1.x docs](https://kagent.dev/docs/kagent/1.x/) | Docs home and full page list |
| [Installation](https://kagent.dev/docs/kagent/1.x/setup/installation/) | Needs Kubernetes 1.37 with `certificates.k8s.io/v1beta1` served. Substrate install steps. `kagent install` cannot set up Substrate yet, so use Helm |
| [Core concepts](https://kagent.dev/docs/kagent/1.x/about/core-concepts/) | Agent pairs an AgentTemplate with a Harness. Session is a conversation in Postgres, not a Kubernetes object. Idle sessions are deleted after 7 days by default |
| [Agent harness](https://kagent.dev/docs/kagent/1.x/agents/agent-harness/) | Runtimes: kagent, claude, codex, byo. Images must be pinned by digest. Only the kagent runtime has structured output |
| [Bring your own agent](https://kagent.dev/docs/kagent/1.x/agents/bring-your-own-agent/) | BYO contract: gRPC A2A on port 80, `/readyz` on 8081, set `KAGENT_PORT=80`. Python `kagent-adk` wraps Google ADK only. Max 32 env vars per actor |
| [agentgateway as model provider](https://kagent.dev/docs/kagent/1.x/setup/model-providers/byo-agentgateway/) | ModelConfig uses provider `OpenAI` with `baseUrl` at the gateway. The `/v1` suffix is required |
| [1.0 release notes](https://kagent.dev/docs/kagent/1.x/reference/release-notes/1.0/) | No in-place upgrade from 0.10. Cannot run beside 0.10 on one cluster. A WorkerPool must exist before an Agent compiles |
| [kagent releases](https://github.com/kagent-dev/kagent/releases) | `v1.0.0-alpha11` came out 2026-10-09. A new alpha ships every few days |
| [Architecture overview](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/docs/architecture/README.md) | Resource ownership, public surfaces (Kubernetes, gRPC, A2A, MCP), and what is not built yet |
| [Runtime and lifecycle](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/docs/architecture/runtime-and-lifecycle.md) | Idle actors are paused or suspended to a snapshot. Egress needs DNS names, not IPs. Durable state lives in `/data` |
| [DEVELOPMENT.md](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/DEVELOPMENT.md) | The dev install path is kind. Substrate chart version comes from `go.mod` (0.5.0-alpha2 at alpha11) |
| [kind cluster config](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/scripts/kind/kind-config.yaml) | Feature gates `ClusterTrustBundle`, `ClusterTrustBundleProjection`, `PodCertificateRequest`, and runtime config `certificates.k8s.io/v1beta1`. The k3d cluster must copy these |
| [kind setup script](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/scripts/kind/setup-kind.sh) | gVisor is the default sandbox class. MicroVMs need working nested KVM |
| [setup-cluster README](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha11/scripts/setup-cluster/README.md) | The Python runtime crashes on golden-snapshot restore with `Fatal Python error: Illegal instruction`. The Go ADK restores cleanly. Source of SPEC.md risk 3 |

## Agent Substrate

| Source | What it told us |
|---|---|
| [Substrate README](https://github.com/kagent-dev/substrate/blob/main/README.md) | Maps many actors onto few worker pods. gVisor and microVM sandboxes. Pre-1.0, no compatibility promise. Supports the latest Kubernetes and the one before |

| [kagent BYO page, A2A wire protocol](https://kagent.dev/docs/kagent/1.x/agents/bring-your-own-agent/) | Checked live 2026-10-09. kagent 1.x speaks gRPC A2A (`lf.a2a.v1.A2AService`) on port 80 |
| kagent controller A2A endpoint (`/agents/<namespace>/<agent>` on the controller, port 8083) | Checked live on k3d-ace in #29, 2026-10-11. The controller serves A2A 1.0 JSON-RPC over HTTP: method `SendMessage`, header `A2A-Version: 1.0`, role `ROLE_USER`, text-only parts, reply in `result.task`, and a session (contextId) that only the agent issues. The invoker and the scripted agent speak this, so no gRPC client is needed. The BYO page was not re-read for this row |

## Cluster

| Source | What it told us |
|---|---|
| [k3s v1.37.1+k3s1](https://github.com/k3s-io/k3s/releases/tag/v1.37.1%2Bk3s1) | A k3s build of Kubernetes 1.37 exists (2026-09-30), with an arm64 image |
| [k3d v5.9.0](https://github.com/k3d-io/k3d/releases/tag/v5.9.0) | The k3d version installed on this Mac |

## Models and gateway

| Source | What it told us |
|---|---|
| [OpenCode Go](https://opencode.ai/docs/go/) | $10 a month. Endpoints under `https://opencode.ai/zen/go/v1/` in three formats: chat completions, responses, and Anthropic messages. Built for coding-agent traffic. Asks for your own user agent and an `x-opencode-session` header. Source of SPEC.md risks 4 and 7 |
| [OpenCode Go model list](https://opencode.ai/zen/go/v1/models) | The live list of model IDs |
| [agentgateway model failover](https://agentgateway.dev/docs/kubernetes/latest/llm/failover/) | Priority groups set failover order. Providers in one group are load balanced. A 429 with `Retry-After` sets the eviction time |
| agentgateway model-call spans (docs/spike-log.md section 18, line 366) | A call the backup group answers carries `gen_ai.provider.name=anthropic`; the failover alert and dashboard count that value. Checked 2026-10-11 against the spike log, not a live page; see https://agentgateway.dev/docs/kubernetes/latest/llm/failover/ |
| [agentgateway rate limiting](https://agentgateway.dev/docs/kubernetes/latest/llm/rate-limit/) | `traffic.rateLimit.local` with `tokens` and `unit` on an HTTPRoute sets a token budget. Over budget the gateway answers 429 with `retry-after` and `x-ratelimit-*` headers. Checked 2026-10-10 |
| [kagent tracing](https://kagent.dev/docs/kagent/1.x/observability/tracing/) | Helm values `otel.traces.enabled` (default false), `otel.exporter.otlp.endpoint` (absolute http(s) URL, the collector's root) and `otel.exporter.otlp.protocol` (`grpc` default, or `http/protobuf`, which appends `/v1/traces`). `scripts/spike/install.sh` sets them when `ACE_OTEL_ENDPOINT` is set. Checked live 2026-10-11 against the 1.x docs, and against the pinned chart: `helm show values oci://ghcr.io/kagent-dev/kagent/helm/kagent --version 1.0.0-alpha9` lists `otel.traces.enabled`, `otel.exporter.otlp.endpoint` and `otel.exporter.otlp.protocol` (`grpc` or `http/protobuf`) |
| [agentgateway traces setup](https://agentgateway.dev/docs/kubernetes/latest/observability/traces/setup.md) | `AgentgatewayPolicy` `spec.frontend.tracing` takes `backendRef` (`name`, `namespace`, `port` 4317), `protocol: GRPC` and `randomSampling: "true"`, and also `clientSampling`. The page does not mention a ReferenceGrant for a collector in another namespace; `manifests/observability/gateway-tracing.yaml` adds one to be safe. Checked 2026-10-11 on the `latest` docs and against the v1.6.0 pin: `helm pull oci://cr.agentgateway.dev/charts/agentgateway-crds --version v1.6.0` holds an `AgentgatewayPolicy` v1alpha1 CRD whose `spec.frontend.tracing` has `backendRef` (`name` required, `namespace`, `port`), `protocol` (enum `GRPC`, `HTTP`), `randomSampling` (string) and `clientSampling` |

## Image signing

Checked on 2026-10-10 against cosign v3.1.3, the version `.github/workflows/publish-images.yml`
installs, with its own `--help` and a local round trip (throwaway key pair, local registry).

| Source | What it told us |
|---|---|
| [cosign v3.1.3 release](https://github.com/sigstore/cosign/releases/tag/v3.1.3) | Latest v3 release on 2026-08-06. Binaries and `cosign_checksums.txt` |
| [cosign-installer v4.1.2](https://github.com/sigstore/cosign-installer/releases/tag/v4.1.2) | Installer action at commit `6f9f1778...`. Its default is cosign v3.0.6; the `cosign-release` input picks v3.1.3, which the installer verifies before it installs |
| `cosign sign --help` (v3.1.3) | `--key env://[ENV_VAR]` reads the private key from an env var; the password comes from `COSIGN_PASSWORD`. `--use-signing-config` defaults to true (the public TUF signing config). `--tlog-upload` is deprecated in favour of a signing config with no transparency log |
| `cosign sign` round trip (v3.1.3) | `--tlog-upload=false` alone fails: "--tlog-upload=false is not supported with --signing-config or --use-signing-config". `--use-signing-config=false --tlog-upload=false` signs, uploads nothing to Rekor, and stores the signature in the new bundle format as an OCI referrer next to the image |
| `cosign verify --help` (v3.1.3) | `--insecure-ignore-tlog` defaults to false: "ignore transparency log verification, to be used when an artifact signature has not been uploaded to the transparency log". With `--insecure-ignore-tlog=true`, `cosign verify --key <pub>` exits 0 on a signature made as above; without it, verify exits 1 |
| [Packages REST API](https://docs.github.com/en/rest/packages/packages#get-a-package-for-a-user) | `GET /users/{username}/packages/container/{package_name}` returns `visibility`. A package name with a slash is URL-encoded (`agentic-campaign-engine%2Face-web`). The page names classic tokens with `read:packages`; it does not say the job token works |
| Grafana alerting provisioning (grafana/otel-lgtm), checked 2026-10-11 | Rules, contact points and policies load from YAML files in the provisioning/alerting folder (grafana/otel-lgtm reads `/otel-lgtm/grafana/conf/provisioning`, where `manifests/observability/collector.yaml` mounts them); a webhook contact point takes `authorization_scheme` and `authorization_credentials`, and `$__env{NAME}` reads an environment variable. Honeycomb takes OTLP at `api.honeycomb.io:443` with header `x-honeycomb-team` |
