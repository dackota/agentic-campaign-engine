# Agentic Campaign Engine

A marketer drops in a threat report. A team of AI agents turns it into a full
campaign. A human approves it. The engine publishes it and learns from the
results.

Runs on Kubernetes (k3d) with [kagent](https://kagent.dev) 1.x and Agent
Substrate.

## The problem

A security team learns about a new threat and wants the market to hear about it fast. Turning
one threat report into a full campaign (emails, a landing page, social posts, a one-pager)
takes a marketing team days of hand-offs between tools. This engine does the drafting with a
team of AI agents, keeps a person in charge of every approval, publishes through the
marketing stack, and feeds what worked back into the next campaign.

The company in the demo, Acme Security, is made up. Every outside system (Marketo,
Workfront, the CMS, the asset store) is a fake we wrote, so the whole thing runs on a laptop.
The only outside need is a model key.

## Demo

The demo shows one Acme Security campaign from threat report to results: paste the report,
watch the agents draft, read the judge's scores, approve as a second person, then see the
A/B winner and the learning it leaves. The spoken script (about four minutes) is
[docs/demo-script.md](docs/demo-script.md); the report to paste is `docs/demo-report.txt`.

Seed the demo data with one command:

    make seed-demo

It loads one finished past campaign for each demo team through the Campaign API, and does
nothing for a team that already has it, so running it twice makes no duplicates. With no
`SEED_ARGS` it seeds a fast-depth stack and prints the steps and judge scores, which are the
same on every run. To seed a running API, pass
`SEED_ARGS="--api-url <url> --tokens-file <file>"`, where the file maps each demo user's email
to a token.

Video: [Watch the demo video](https://example.com/owed-demo-video). The link is a
placeholder: the recording is owed, and the user adds the real link here once it is made. The demo GIF is owed too: it needs a screen recorder and a GIF converter,
and would be saved as `docs/demo.gif` (under 5 MB).

## Job bullet to proof

Each row is a requirement from the job this project answers. The links go to the code, then
to the tests that prove it. A tick in "Live check" means the proof runs against the real
cluster and is not run in CI; "owed" means that live check has not run yet.

| Job bullet | Code | Tests | Live check |
|---|---|---|---|
| Build integrations (Workfront, Marketo, Docs, Slack, CMS, DAM) | [fakes](services/fakes/README.md), [MCP servers](services/mcp/README.md), [Slack and Docs](apps/worker/campaign_worker/notify.py) | [Marketo](tests/api/test_marketo_fake.py), [Workfront](tests/api/test_workfront_fake.py), [Slack and Google](tests/api/test_slack_google_fakes.py), [CMS and S3](tests/api/test_content_fakes.py), [MCP](tests/mcp/test_mcp_servers.py) | Real Slack and Google Docs are off unless their credentials are set; not run live. [ADR](docs/decisions/mcp-servers.md) |
| Orchestration layer: multi-agent pipelines, state, error recovery, parallel runs | [workflow](apps/worker/campaign_worker/workflow.py), [DAG rules](apps/engine/ace_engine/dag.py), [agent call](apps/engine/ace_engine/invoker.py) | [runs](tests/api/test_workflow_runs.py), [step failures](tests/api/test_step_failures.py), [DAG property](tests/api/test_workflow_property.py), [default workflow](tests/api/test_default_workflow.py) | Live agents on the cluster: owed. [ADR](docs/decisions/temporal-dag-engine.md) |
| Web UIs for non-technical users | [React app](apps/web/src/App.tsx), [workflow builder](apps/web/src/Builder.tsx), [inbox](apps/web/src/Inbox.tsx), [run view](apps/web/src/RunGraphView.tsx) | [builder](apps/web/e2e/workflow-builder.spec.ts), [approve](apps/web/e2e/approve.spec.ts), [inbox](apps/web/e2e/inbox.spec.ts), [run graph](apps/web/e2e/run-graph.spec.ts), [dashboard](apps/web/e2e/dashboard.spec.ts) | Browser tests run on the fast stack. |
| Production tooling: HTML email, PPTX, PDF, SVG, publishing | [render service](services/render/README.md), [publisher](apps/worker/campaign_worker/publisher.py), [design agent script](scripts/design-sandbox.sh) | [email](tests/render/test_render_email.py), [assets](tests/render/test_render_assets.py), [design cards](tests/api/test_design_cards.py), [publish](tests/api/test_content_publish.py), [sandbox program](tests/tooling/test_sandbox_program.py) | The design agent in a live sandbox: owed. [ADR](docs/decisions/sandbox-design-agent.md) |
| Analytics: dashboards, quality scoring, A/B tests, feedback loops | [judge](apps/engine/ace_engine/judge.py), [A/B result](apps/api/campaign_api/ab_result.py), [learnings](apps/engine/ace_engine/learnings.py), [webhooks](apps/api/campaign_api/webhook_routes.py) | [A/B](tests/api/test_ab_result.py), [judge](tests/api/test_judge.py), [learnings](tests/api/test_learnings.py), [Marketo webhooks](tests/api/test_marketo_webhooks.py), [dashboard](tests/api/test_dashboard.py) | The click rate rising with learnings on: owed, see [learning proof](docs/learning-proof.md). [ADR](docs/decisions/learnings-store.md) |
| Custom AI agents with MCP servers and enterprise systems | [AgentTemplates](agents/templates.yaml), [MCP bindings](agents/mcp.yaml), [MCP servers](services/mcp/ace_mcp/server.py) | [agent roles](tests/tooling/test_agent_roles.py), [MCP tools](tests/tooling/test_mcp_tools.py), [team agents](tests/tooling/test_team_agents.py), [MCP reads](tests/api/test_agent_mcp_reads.py) | AgentTemplates at live depth: owed. The custom Python agent is a stretch that is not built; the spike result is in the [ADR](docs/decisions/python-byo-wakeup.md) and [its test](tests/spike/test_python_byo_spike.py). |
| Auth, permissions, multi-tenancy | [sign-in and roles](apps/api/campaign_api/auth.py), [row-level security](apps/engine/ace_engine/row_security.py), [team agents](agents/teams/gateway.yaml) | [access](tests/api/test_access.py), [team isolation](tests/api/test_team_isolation.py), [row security](tests/engine/test_row_security.py), [login](apps/web/e2e/login.spec.ts) | Two teams at once on the cluster: owed. [ADR](docs/decisions/team-isolation.md) |
| CI/CD and reliability | [CI workflows](.github/workflows/test.yml), [eval gate](evals/gate.py), [signed images](.github/workflows/publish-images.yml), [alerts](docs/decisions/dashboards-and-alerts.md) | [gate](tests/evals/test_gate.py), [alerts](tests/api/test_alerts.py), [image build](tests/tooling/test_image_build_workflow.py), [publish workflow](tests/tooling/test_publish_images_workflow.py), [observability](tests/tooling/test_observability.py) | Signed images run after a merge to main: owed. The nightly k3d run is not built. [ADR](docs/decisions/eval-gate.md) |
| Performance: caching, parallelism, LLM cost | [step cache](apps/engine/ace_engine/step_cache.py), [step limits](apps/engine/ace_engine/limits.py), [cost](apps/engine/ace_engine/cost.py), [budget](apps/api/campaign_api/budget.py), [load script](tests/harness/load.py) | [step cache](tests/api/test_step_cache.py), [team step limit](tests/api/test_team_step_limit.py), [cost](tests/api/test_campaign_cost.py), [gateway failover](tests/tooling/test_gateway_failover.py), [load script](tests/api/test_load_script.py) | Failover with a real Anthropic key and the 20-campaign load test: owed, see [load test](docs/load-test.md). [ADR](docs/decisions/step-cache.md) |
| Partner with marketing leadership | This README, [architecture](docs/architecture.md), [decisions](docs/decisions/README.md) | [README](tests/tooling/test_readme.py), [doc links](tests/tooling/test_docs_links.py) | The video: owed. |

How the owed items get closed: one live check on the cluster after merge. The list of what
it covers is kept with the project's working notes.

## Architecture and decisions

- [docs/architecture.md](docs/architecture.md): the parts, and the four flows (campaign run,
  approval and publish, webhooks and learnings, auth and team isolation).
- [docs/decisions/README.md](docs/decisions/README.md): every big decision and the ADR for it.
- [SPEC.md](SPEC.md): the plan, the pipeline rules, and the slices.

## Quick start

    git clone https://github.com/dackota/agentic-campaign-engine.git
    cd agentic-campaign-engine
    cp .env.example .env      # then add your key; see "Set up .env"
    make up                   # about the time it takes to build a cluster and pull images

Then open http://127.0.0.1:15180/ and sign in (see "Use the app"). `make help` lists every
target. If `make up` stops at `env-check`, it names the missing tool or `.env` name.

## Tests

Two seams, no others: the Campaign API (HTTP, the run event stream, webhooks) and the
browser (Playwright). `make test` runs both at fast depth with a scripted agent and needs
only Docker. `make evals` runs the golden set against the baseline. Row-level security is
the only team filter, so the API tests prove the database rule too.

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
- `HONEYCOMB_API_KEY`: optional. Set, `make up FULL=1` also exports traces and metrics
  to Honeycomb; empty, it does not.

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
