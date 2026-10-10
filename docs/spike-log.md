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

## 11. Not done

Python BYO agent (`kagent-adk`): not built or run. It needs an image in a registry the
node can pull from. The decision is in `docs/decisions/k3d-or-kind.md` (S13: no).

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
