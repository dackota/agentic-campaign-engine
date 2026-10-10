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
