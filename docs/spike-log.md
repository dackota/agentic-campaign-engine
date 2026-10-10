# Spike log: kagent 1.x on k3d (S0)

Date: 2026-10-09 (cluster clock shows 2026-10-10 UTC). Machine: Apple Silicon Mac,
Docker Desktop 8 CPUs, 23.4 GiB, untouched. Cluster `ace-spike`, kube context
`k3d-ace-spike`. Every `kubectl` call passes `--context`. Total hands-on time for
the k3d fixes: well under the one-day box.

Scripts and manifests in this repo reproduce the working state:
`k3d/ace-spike.yaml`, `scripts/spike/install.sh`, `manifests/spike/*`,
`scripts/spike/a2a-smoke.sh`. Versions are in `docs/pinned-versions.md`.

## 1. Read the docs

Read the install guide, harness, BYO, first-agent and A2A pages. The guide pins
kagent 1.0.0-alpha9 and Substrate 0.4.0-alpha1. `docs/sources.md` named alpha11
and 0.5.0-alpha2. The guide has no Harness/AgentTemplate/Agent YAML in one place
and no HTTP A2A example (only `grpcurl`).

## 2. Red test

```
scripts/spike/a2a-smoke.sh > .lane/red.log 2>&1
FAIL: missing or empty docs/spike-log.md      (exit 1)
```

## 3. Cluster

```
k3d cluster create --config k3d/ace-spike.yaml --wait --timeout 180s
```

Config: `rancher/k3s:v1.37.1-k3s1`, `runtime-config=certificates.k8s.io/v1beta1=true`,
and the `ClusterTrustBundle`, `ClusterTrustBundleProjection`, `PodCertificateRequest`
gates on kube-apiserver, kubelet and controller-manager.

Result: created in 18 s. `kubectl --context k3d-ace-spike get nodes` shows
`v1.37.1+k3s1`; `api-versions` lists `certificates.k8s.io/v1beta1`. k3d needed no
fix for the runtime config or the gates (risk 2: answered yes).

## 4. Substrate 0.5.0-alpha2 attempt (failed, abandoned)

Followed the guide's steps with the newest versions (`kubectl-ate` v0.5.0-alpha2).

Error 1:
```
Error: while uploading pool state to secret: namespaces "podcertificate-controller-system" not found
```
Fix tried: create that namespace (`kubectl --context k3d-ace-spike create namespace ...`). Pools then
created.

Error 2: after `helm upgrade ... --wait` every pod in `ate-system` stuck in
`ContainerCreating`:
```
MountVolume.SetUp failed for volume "podidentity": credential bundle is not issued yet ...
```
`kubectl --context k3d-ace-spike get podcertificaterequests -A` showed all requests `Pending`. Cause:
0.5.0-alpha2 does not deploy the certificate controller; it ships in a separate
`substrate-podcert` chart, and PostgreSQL moved out too
(`hack/install-postgres.sh`, `postgres.clientCertificates.enabled`). The guide covers
neither.

Fix: do not fight it. Uninstalled both releases, deleted the namespaces, and used the
pair the guide documents (Substrate 0.4.0-alpha1, kagent 1.0.0-alpha9). Draft bug 1.

## 5. Substrate 0.4.0-alpha1 + kagent 1.0.0-alpha9

```
curl -fsSL -o kubectl-ate .../v0.4.0-alpha1/kubectl-ate-darwin-arm64
```
Error 3: the first run of the script printed `Killed: 9` for `kubectl-ate` (macOS
killed the freshly downloaded binary). Fix: `codesign --force -s - kubectl-ate`.

`scripts/spike/install.sh` runs, in order: `substrate-crds`, `substrate` (with the
`namespacePolicies` grant), CA pools (`service-dns`, `pod-identity`, `actor-id`
CA+JWT, `egress-mitm` ECDSA P-256), the `actor-id-ca-certs` secret, the
`ate-api-authentication` ConfigMap, a `--reuse-values --wait` rollout, `kagent-crds`,
and `kagent` with a WorkerPool on `ateom-gvisor` pinned by digest. The 0.4.0 chart
creates the pod-certificate controller and PostgreSQL itself. Total about 3 minutes.
All Substrate and kagent pods Running. The model key is a placeholder; a scripted
model (`manifests/spike/mock-llm.yaml`) stands in for a real LLM, no outside account.

## 6. Agent apply

```
kubectl --context k3d-ace-spike apply -f manifests/spike/mock-llm.yaml -f manifests/spike/agent.yaml
```
Harness (`golang-adk` by digest), AgentTemplate, Agent, ModelConfig.

Error 4: Agent `Ready=False`, `GoldenActorCrashed: golden actor crashed before its snapshot was taken`.
The status gives no cause. Worker pod log (`kubectl --context k3d-ace-spike logs -n kagent kagent-default-...`),
`RunWorkload` response:
```
while composing pause rootfs: while mounting overlay rootfs at ".../bundles/_pause/rootfs":
while setting overlay upperdir=".../bundles/_pause/upper": invalid argument
(kernel: overlay: filesystem on .../upper not supported as upperdir)
```
Cause: `/var/lib/ate` is a hostPath on the node, and in k3d the node's own root is
overlayfs; the kernel refuses an overlayfs upperdir on overlayfs.

Fix (k3d only): mount a Docker volume at `/var/lib/ate` (`volumes:` in
`k3d/ace-spike.yaml`). Deleted the cluster, recreated with the volume, reran
`install.sh` and the apply. Agent `Ready=True`. Draft bugs 2 and 3.

## 7. A2A

The agent card advertises JSON-RPC at `/agents/kagent/spike-agent`, protocol 1.0.

Error 5: `method: "message/send"` returns `-32601 method not found`. The 1.0
method is `SendMessage`, with `role: "ROLE_USER"` and parts `{"text": ...}`.
```
curl -H 'content-type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m1","role":"ROLE_USER","parts":[{"text":"What is 7 times 6? Answer with just the number."}]}}}' \
  localhost:18083/agents/kagent/spike-agent
```
Answer: artifact text `42`, state `TASK_STATE_COMPLETED`.
`scripts/spike/a2a-smoke.sh` does this against a port-forward and exits 0.

## 8. Idle suspend and wake

`kubectl ate --context k3d-ace-spike get actors -A` showed the session actor `ACTOR_STATE_SUSPENDED` within a
minute of the first answer, with no worker pod. A second `SendMessage` on the same
`contextId` returned in 0.2 s and the actor was `ACTOR_STATE_RUNNING`. Suspend and wake
work on the Go harness.

## 9. Standalone sandbox

`kagent` CLI 1.0.0-alpha9, `--api-url` pointed at the port-forward.

Error 6: a SandboxTemplate (alpine by digest) stayed `PreparationFailed`; `create`
said `SandboxTemplate has no prepared revision`. Controller log:
`sandbox workload and guest images must be pinned by sha256 digest`. The chart's
`controller.sandbox.guestImage.digest` defaults to empty, so the guest image has no
digest. Fix: set `controller.sandbox.guestImage.digest` to the `sandbox-guest:1.0.0-alpha9`
digest (`manifests/spike/kagent-values.yaml`), `helm upgrade`. Template `Prepared`.
Draft bug 4.

Also learned: SandboxTemplate `spec.workload` accepts only `image` (no `command`).
```
# kagent CLI talks to the controller through the port-forward, not a kube context
kagent --api-url http://localhost:18083 --gateway-url http://localhost:18083 sandbox create spike-sandbox --request-id s0-2 --name spike   -> RUNTIME_STATE_READY
kagent sandbox exec <id> -- uname -a   -> Linux actor 4.19.0-gvisor ... aarch64, exit 0
```

## 10. RAM

`docker stats` on the k3d node, platform plus one suspended session and the mock
model, idle: 2.27 GiB of 23.4 GiB. `kubectl --context k3d-ace-spike top pods -A`: `atelet` 310 Mi, kagent
controller 70 Mi, rustfs 73 Mi, the two Postgres 57 Mi each, the rest under 50 Mi.

## 11. Python BYO agent

Done in section 15 (ticket S0 Python wake-up test).

## 12. Final

Smoke script, after docs written: prints `42`, exit 0. `kubectl --context k3d-ace-spike
get harness,agenttemplate,agent -A` shows the three; Agent `Ready=True`. Harness image
is `ghcr.io/kagent-dev/kagent/golang-adk@sha256:26ae5c77...`. The cluster is left running.

## 13. Readiness of Harness and AgentTemplate (review round 1)

`kubectl --context k3d-ace-spike get harness,agenttemplate,agent -A` shows READY only
for the Agent. Checked against the CRDs and the live objects:

- `agenttemplates.api.kagent.dev` v1alpha3 has no `status` in its schema, no status
  subresource, and its only printer column is Age. Template readiness is by design:
  a template is ready when the Agent that uses it is. `.status` on `spike-template` is null.
- `harnesses.api.kagent.dev` v1alpha3 defines `status` (`capabilities`, `conditions`,
  `observedGeneration`), a status subresource and a Ready printer column. On
  1.0.0-alpha9 the controller never writes it: `kubectl --context k3d-ace-spike get harness spike-harness -n kagent -o json | jq .status`
  is `null` even while the Agent is Ready and answering. Upstream bug, draft 5.

Replacement proof (the Agent's Ready condition covers the Harness, since the Agent
compiles from the template and Harness and its golden actor must snapshot first):
```
kubectl --context k3d-ace-spike get harness spike-harness -n kagent -o jsonpath='{.spec.workload.image}'
   -> ghcr.io/kagent-dev/kagent/golang-adk@sha256:26ae5c77...   (digest pin)
kubectl --context k3d-ace-spike get agent spike-agent -n kagent -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
   -> True
scripts/spike/a2a-smoke.sh   -> 42, exit 0
```
The smoke script already asserts both the digest pin and Agent Ready; unchanged.

## 14. S1: agents call models through agentgateway

agentgateway v1.6.0 (`agentgateway-crds` and `agentgateway` charts, `cr.agentgateway.dev`)
in `agentgateway-system`. `scripts/spike/gateway-install.sh` installs it, makes Secret
`opencode-go-key` (key `Authorization`) from `OPENCODE_KEY` in `.env`, and applies
`manifests/spike/gateway.yaml`: a Gateway, an `AgentgatewayBackend` (host `opencode.ai`,
path `/zen/go/v1/chat/completions`, TLS, auth from the Secret), an HTTPRoute on `/v1`, and
ModelConfig `gateway-model` with `baseUrl` `http://agentgateway-proxy.agentgateway-system.svc.cluster.local/v1`.
`spike-template` now uses `gateway-model` (model `glm-5.3-flash`). The ModelConfig still
names the placeholder `kagent-openai` Secret, which holds `spike-not-a-real-key`.

`scripts/spike/gateway-check.sh` (live, `make gateway-check`) saw: spike agent answers
`42`; gateway log shows `http.status=200 gen_ai.usage.input_tokens=301
gen_ai.usage.output_tokens=29` for the call; OpenCode headers `user-agent:
agentic-campaign-engine/0.1` and `x-opencode-session`; no pod outside `agentgateway-system`
has a provider key in env or mounted Secrets, and the key value is in no other Secret.
Output saved in `.scratch/ace/proof/23-gateway-check.txt`.

Sources, checked 2026-10-10: `docs/sources.md` rows "agentgateway as model provider"
(ModelConfig provider `OpenAI`, `baseUrl` at the gateway, `/v1` required), "OpenCode Go"
(endpoint `https://opencode.ai/zen/go/v1/chat/completions`, own user agent,
`x-opencode-session`) and "agentgateway model failover". Live pages read the same day:
https://kagent.dev/docs/kagent/1.x/setup/model-providers/byo-agentgateway/ (the `/v1`
suffix is required; kagent appends `/chat/completions`) and https://opencode.ai/docs/go/
(asks for a stable `x-opencode-session` per conversation). Both match the manifests.

Limit of the pod key check: the agent runs as a Substrate sandbox inside the WorkerPool
pod (`ate.dev/worker-pool=kagent-default`), not as its own pod. `gateway-check.sh` says
which WorkerPool pod it saw, checks the Harness, WorkerPool and SandboxTemplate specs for
env and secret refs, and prints that the process env inside the sandbox is not checked:
the cluster API does not show it. The WorkerPool pod's own env is in the pod check.

Learned: the HTTPRoute `RequestHeaderModifier` runs before the access log, so an
`AgentgatewayPolicy` (`frontend.accessLog.attributes`) can print the headers OpenCode gets.

### x-opencode-session: per agent, not per conversation

The header is set per agent today. The route filter sets a fixed value. kagent
ModelConfig has `spec.defaultHeaders`, also a fixed map per ModelConfig, and the golang
ADK harness offers no per-request header hook. So one value per ModelConfig (one per agent
if each agent gets its own) is what we can do. A per-conversation value would need the
runtime to add the Session id to each model call; nothing in kagent 1.0.0-alpha9 does that.
Open risk: OpenCode may read a constant session as one very long conversation.
Revisit if OpenCode throttles or caches by session.

## 15. Python BYO wake-up test (#22)

Result: crashed (stock image), survived (with a fast readiness endpoint).

Agent: `kagent-adk` pinned by digest `sha256:f60b442f...` (`manifests/spike/python-byo.yaml`).
The agent code is inline in `spec.workload.command` (a `BaseAgent` that answers `42 boot=<id>
pid=<pid> n=<count>`), so no registry is needed. `byo: {}`, `KAGENT_PORT=80`, `/readyz` on 8081.
Driver: `scripts/spike/python-wakeup.sh` (live; `AGENT=` picks the manifest's Agent).

Run 1, `s22-py-agent` (stock):
- Phase 1: answered `42 boot=... n=1`. The golden snapshot restored in about 0.1 s.
- Suspend: actor reached `ACTOR_STATE_SUSPENDED`.
- Phase 2: the wake never completed. The actor stayed `ACTOR_STATE_RESUMING`; the controller
  answered `KAGENT_SEND_NOT_ACCEPTED` for 40 retries. Atelet log, each attempt:
  `Restore timing breakdown ... snapshot.scope=data snapshot.kind=latest error.type=Canceled
  ateom_restore=4.98s`. Ateom logs `Actor restoring`, then runsc create and start, and no
  `Wakeup probe reached 200`. It retries every 6 s, forever (39 attempts in 5 minutes).
- No `Illegal instruction` or `Fatal Python error` anywhere. The failure is not kagent's
  CPU crash; on this arm64 stack it is a timeout.

What the logs show: a wake restores the `latest` snapshot with scope `data`. That keeps the
filesystem and starts the process cold (the golden snapshot is `full`). The process boots
again and Substrate waits about 5 s for `/readyz`. The Go harness answers in 0.1 s. The
Python image needs more than 5 s for its imports, so the probe is cancelled and retried.

Run 2, `s22-pyfast-agent` (`manifests/spike/python-byo-early-readyz.yaml`): same agent, plus a
stdlib thread that answers `/readyz` on 8081 before the heavy imports start (the port is
shared with `SO_REUSEPORT` so kagent-adk still binds it). Two runs, both:
- Phase 1: `42 boot=6d9f3a99 pid=1 n=1`, then phase 2 `42 boot=337975ae pid=1 n=1`.
- The boot id and counter changed: the wake is a fresh process, not a memory restore. Keep
  nothing in process memory that must survive a wake (true for Go too, by the scope above).
- `Wakeup probe reached 200` after 0.36 s; atelet `ateom_restore` 0.42 s.

Upstream bug: draft 6, `docs/upstream-bugs/6-python-byo-wake-never-completes.md`.
Decision: `docs/decisions/python-byo-wakeup.md`.
## 14. Suspend and wake with context (S21)

`scripts/spike/suspend-wake.sh` (live depth, exits 0 only on success). The mock model
(`manifests/spike/mock-llm.yaml`) now answers "What is the code word?" from an earlier
"The code word is X" in the history the harness sends it. A model that sees no history
says "I do not know the code word", so a lost context fails the script.

Run: message 1 sets the code word `violet-otter-17` on a new session. The actor
`session-<contextId>` (`kubectl-ate get actors -A`) was `ACTOR_STATE_SUSPENDED` by the time the
first poll ran, a few seconds after the reply, with no worker pod. Message 2 on the same
`contextId` woke it (`ACTOR_STATE_RUNNING`) and the reply was `The code word is violet-otter-17`.
Whole script: about 4 s. So idle suspend is eager in this config: the harness suspends right
after a turn ends, there is no minutes-long idle timer to wait for. (The earlier
"within a minute" note in section 8 was only the first poll.)

Gotchas: the `kubectl-ate get actors` columns shift when a worker pod is absent (`<none>`),
so read the state from column 4, not by position from the right. A2A sessions are the actors
named `session-<contextId>`; the session id is the contextId the first reply returns.

## 15. Standalone sandbox (S21)

`scripts/spike/sandbox.sh`: `kagent sandbox create spike-sandbox --request-id ... -o json`
returns `RUNTIME_STATE_READY` at once (the template is already prepared), `exec` prints
`hello from s21 sandbox` with exit 0, `delete` then `get` shows `RUNTIME_STATE_DELETED`.
The script deletes the sandbox on any failure too. A sandbox gets a default 1 h TTL
(`expiresAt`; activity does not extend it).

## 16. Sandbox network limits (for the design agent ticket)

Measured from inside a sandbox (gVisor, alpine, root, 2 CPUs, 1024 MiB RAM, `/data` is a
shared 165 GiB disk view). Default template, no network settings. The SandboxTemplate CRD
(`api.kagent.dev/v1alpha3`) has no egress or network field: only `workload.image`, `env`,
`substrate`. `SandboxConfig` (ate.dev) has only `assets`, `pauseImage`, `sandboxClass`.

| Probe from the sandbox | Result |
|---|---|
| DNS (`nslookup example.com`) via 169.254.17.1 | works, returns real A and AAAA records |
| Outbound HTTP and HTTPS to `example.com` | `HTTP/1.1 403 Forbidden` (the egress proxy answers) |
| Outbound to in-cluster services (`kagent-controller`, `mock-llm`, the API server ClusterIP) | `403 Forbidden` |
| Cloud metadata address 169.254.169.254 | `403 Forbidden` |
| ICMP ping to 1.1.1.1 | 100% loss |
| Proxy environment variables | none set; the redirect is transparent |

Reading: egress is deny-by-default and goes through Substrate's `atenet-egress` proxy (the
`egress-mitm` CA pool made in the install). Ingress (inferred, not probed): nothing reaches the sandbox except
`kagent sandbox exec/upload/download` through the controller; the sandbox has no
inbound route of its own. The design agent ticket must therefore not assume a sandbox can
fetch a package, call an API, or reach the MCP tools service. Work in a sandbox is limited to
code and files pushed in with `upload`, with results pulled out with `download`/`exec`. No way
to allow-list a host was found in alpha9 (draft bug 6). Not tested: whether an egress policy
exists on the Substrate side (`atenet-egress` config) and the HTTP 403 for an allowed host.

## 17. Platform RAM (S21)

Measured 2026-10-10 on the k3d node with `kubectl --context k3d-ace-spike top pods -A`, all
sessions suspended, no sandbox running. Docker Desktop VM 23.4 GiB.

| Part | RAM |
|---|---|
| Substrate (`ate-system`: atelet 247, rustfs 177, postgres 60, api-server 80, controller 21, atenet 71, credential provider 12) | 668 MiB |
| Pod certificate controller | 17 MiB |
| kagent (controller 89, postgresql 65, grafana-mcp 20, tools 20, kmcp 18, ui 3) | 215 MiB |
| **Platform alone (the three rows above)** | **about 900 MiB** |
| WorkerPool worker pod `kagent-default` (one warm worker, holds the running actors) | 535 MiB |
| k3s system pods (coredns, traefik, metrics-server, provisioner) | 94 MiB |
| Platform plus worker plus k3s system | about 1.5 GiB |
| Mock model server | 11 MiB |
| `docker stats` for the whole k3d node container | 3.44 GiB (page cache, containerd, kubelet; and ticket 22's agentgateway, 53 MiB, was installed at the time) |

A suspended session costs no pod RAM: its state is a snapshot in rustfs. Budget for the
demo laptop: about 1 GiB for the platform, about 0.5 GiB per warm worker, plus whatever the
running agents and the control plane's own node use. 2.3 GiB at the end of S0 (section 10)
and 3.44 GiB now are both node totals; the pod sums above are the number to design to.

## 18. S1: failover and team token limits

Run 2026-10-10 on k3d-ace-spike, agentgateway v1.6.0. Decision record:
`docs/decisions/llm-gateway-failover.md`.

**Cross-style failover: failover works across an OpenAI-style and an Anthropic-style
provider in one priority list.** The `opencode-go` backend now has two priority groups:
OpenCode Go (provider `openai`, chat completions) and an Anthropic-style provider
(provider `anthropic`). There is no Anthropic key yet, so group 2 is the in-cluster mock's
new `/v1/messages` route (`manifests/spike/mock-llm.yaml`), which answers in the Anthropic
Messages shape, streamed or not. The client sends OpenAI chat completions. agentgateway
turns the request into an Anthropic Messages call and turns the answer back into a chat
completion (`"model":"mock-anthropic"`, content `42`). No fallback was needed: we keep
one list with both styles.

Broken key test (`scripts/spike/gateway-failover-check.sh`, `make gateway-failover-check`):
the `failover-test` backend (`manifests/spike/gateway-failover-test.yaml`) copies the
groups but gives OpenCode Go a fixed fake key. OpenCode answers 401 (`Invalid API key.`).
The health policy evicts group 1 on 401, 403 or 5xx after one failure. A route retry
policy (one attempt, 1s backoff) then sends the same call to group 2, and the client gets
200. Without the backoff, the retry went back to OpenCode before the eviction, and the
client got the 401. The gateway log prints one line per request, for the last attempt:
`route=agentgateway-system/failover-test endpoint=mock-llm.kagent.svc.cluster.local:8000
http.status=200 gen_ai.provider.name=anthropic gen_ai.request.model=mock-anthropic
retry.attempt=1`. That line shows the switch: a retried call that group 2 answered. The
401 attempt itself gets no access log line.

Team token limits: each team has a ModelConfig (`team-a-model`, `team-b-model`) whose
`baseUrl` is its own route (`/team-a/v1`, `/team-b/v1`). Each route has its own
`traffic.rateLimit.local` budget, 10000 tokens a minute (a spike number; S6 sets the real
ones). The route sets `x-team`, and the access log prints it as `team="team-a"` next to
`gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`; the check sums both per
team. In the check, team-a got 429 (`reason=RateLimit`) on its
third 8k-token call. team-b's call in the same minute got 200 from `opencode.ai`.

Learned, and fixed: the gateway's own rate-limit 429 counts against the backend's health.
With `response.code == 429` in the unhealthy rule, team-a going over its budget evicted
OpenCode Go, and team-b's next call went to group 2. The rule now leaves out 429, and so
does the retry list. A provider 429 still lowers health, and its `Retry-After` sets the
wait (agentgateway failover docs). Open: OpenCode Go quota exhaustion now fails over more
slowly than a bad key does.

Sources, checked 2026-10-10: `docs/sources.md` rows "agentgateway model failover" and
"agentgateway rate limiting". Live pages read the same day:
https://agentgateway.dev/docs/kubernetes/latest/llm/failover/ (priority groups,
`backend.health` eviction, retry needs eviction first, mixed provider types) and
https://agentgateway.dev/docs/kubernetes/latest/llm/rate-limit/ (`traffic.rateLimit.local`
with `tokens` and `unit`, 429 with `retry-after` and `x-ratelimit-*` headers). Both match
the manifests and what the check saw.

Owed after the merge: the real Anthropic run. When the user adds `ANTHROPIC_API_KEY` to
`.env`, `scripts/spike/gateway-install.sh` makes Secret `anthropic-key` and applies
`manifests/spike/gateway-anthropic.yaml` (group 2 becomes `api.anthropic.com`, model
`claude-haiku-4-5`). Then the broken key run needs repeating against the real API.
