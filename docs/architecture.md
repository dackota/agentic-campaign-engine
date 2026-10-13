# Architecture

How a campaign moves through the engine. Each diagram follows the code on this branch; the
file names under each one are where to read the real thing. The component list and the
reasons for each choice are in [SPEC.md](../SPEC.md) and the [decisions index](decisions/README.md).

## The parts

```mermaid
flowchart TB
  U[Marketer] --> WEB[React app<br/>apps/web]
  WEB -->|OIDC login| DEX[Dex]
  WEB -->|REST and SSE| API[Campaign API<br/>apps/api]
  API --> PG[(Postgres + pgvector<br/>row-level security)]
  API -->|start, signal| TMP[Temporal]
  TMP --> WK[Worker<br/>apps/worker]
  WK -->|A2A| KAG[kagent Agents]
  KAG -->|model calls| AGW[agentgateway]
  AGW -->|first| OCG[OpenCode Go]
  AGW -->|on failure| ANT[Anthropic API]
  KAG -->|read-only MCP| MCP[MCP servers<br/>services/mcp]
  MCP --> FAKES[Fakes: Marketo, Workfront, CMS, S3<br/>services/fakes]
  WK --> RND[Render service<br/>services/render]
  WK -->|publish| FAKES
  FAKES -->|signed webhooks| API
```

## Campaign run

The API pins the workflow DAG to the run and starts one Temporal workflow. The workflow
starts every ready step of a wave at the same time. An agent step asks one kagent Agent over
A2A, checks the reply against the step's JSON Schema (one repair try), and saves it. The
brand reviewer can send a writer back for fixes, up to a set number of rounds. The judge
scores every asset; a score under the floor stops the run and names the asset.

```mermaid
sequenceDiagram
  participant API as Campaign API
  participant T as Temporal workflow
  participant A as Worker activity
  participant C as Step cache
  participant K as kagent Agent
  participant G as agentgateway
  participant DB as Postgres
  API->>DB: save campaign with its pinned DAG
  API->>T: start workflow (campaign id, report, DAG)
  loop each wave of ready steps, in parallel
    T->>A: run agent step (takes a team step slot)
    A->>C: look up (step type, agent digest, input hash)
    alt cache hit
      C-->>A: saved output, no model call
    else miss
      A->>K: A2A message with the output schema
      K->>G: model call
      G-->>K: reply, or failover to the second model
      K-->>A: JSON output plus token usage
      A->>A: check schema, repair once, check citations
      opt brand reviewer on this step
        A->>K: review the draft, send fixes back (max rounds)
      end
    end
    A->>DB: save output, cost, step status
    A-->>T: step result
  end
  T->>DB: judge scores saved, run waits for approval
```

- DAG rules: `apps/engine/ace_engine/dag.py`. Workflow: `apps/worker/campaign_worker/workflow.py`.
- Agent call and schema check: `apps/engine/ace_engine/invoker.py`. Step cache:
  `apps/engine/ace_engine/step_cache.py`. Team step slots: `apps/engine/ace_engine/limits.py`.
- A failed step stops the run with its reason. The owner's retry signal re-runs the
  unfinished steps of that wave. A spent budget pauses the step until the owner raises it.
- Live progress reaches the browser as server-sent events from `GET /campaigns/{id}/events`.

## Approval and publish

Agents read. The engine writes. A publish step runs only after an approval step, and the API
rejects a workflow where it would not.

```mermaid
sequenceDiagram
  participant H as Approver
  participant W as Web app
  participant API as Campaign API
  participant T as Temporal workflow
  participant P as Publisher
  participant F as Fake Marketo, CMS, S3
  participant S as Slack (by flag)
  T->>API: run waits for approval (agents idle)
  H->>W: open the approval inbox, preview assets
  W->>API: POST /campaigns/{id}/approve
  API->>API: role check: approver, not the campaign's creator
  API->>T: approve signal
  Note over T: a rejected asset is signalled with a comment and redone
  T->>P: send_email, then publish_content
  P->>F: send email, publish page, store assets (idempotency key per target)
  F-->>P: receipts
  T->>API: mark sent, save receipt
  T->>S: announce published (only when Slack is set up)
```

- Role rules: `apps/api/campaign_api/auth.py`. Publisher: `apps/worker/campaign_worker/publisher.py`.
- Slack notices and the Google Doc export: `apps/worker/campaign_worker/notify.py`.

## Webhooks and learnings

The fake Marketo plays a simulated audience. It posts signed activity events back to the API.
The API counts opens and clicks per variant, and when the A/B test can call a winner it keeps
the winning lines as a learning. The research and writer agents search learnings before they
write.

```mermaid
flowchart LR
  FM[Fake Marketo<br/>simulated audience] -->|signed activity webhook| WH[API webhook route]
  FW[Fake Workfront] -->|signed task status webhook| WH
  WH -->|size cap, signature check,<br/>once per event id| ACT[(activity rows)]
  ACT --> AB{A/B test<br/>can call a winner?}
  AB -- no --> WAIT[wait for more events]
  AB -- yes --> EMB[Embed winning lines]
  EMB --> LRN[(learnings table<br/>pgvector)]
  LRN -->|search_learnings, read-only MCP| AG[Research and writer agents]
  AG -.next campaign.-> RUN[Campaign run]
  ACT --> DASH[Team dashboard<br/>click rate, quality]
```

- Webhooks: `apps/api/campaign_api/webhook_routes.py`. Winner rule: `apps/api/campaign_api/ab_result.py`.
- Learnings store: `apps/engine/ace_engine/learnings.py`; the tool the agents call is in
  `services/mcp/ace_mcp/learnings.py`.
- Each campaign is one OpenTelemetry trace; later requests and webhooks join it
  ([one-trace-per-campaign.md](decisions/one-trace-per-campaign.md)).

## Auth and team isolation

Dex issues the token. The API reads the team and the role from the token and opens the
database as that team. The database, not the API's queries, filters rows.

```mermaid
sequenceDiagram
  participant B as Browser
  participant D as Dex (OIDC)
  participant API as Campaign API
  participant PG as Postgres
  B->>D: sign in (demo user)
  D-->>B: token with groups team:id and role:name
  B->>API: request with bearer token
  API->>D: verify token
  API->>API: authorize(role, action)
  API->>PG: connect as ace_team, set ace.team = user's team
  PG-->>API: only that team's rows (row-level security)
  Note over API,PG: worker and signed webhooks connect as the table owner<br/>and act for the system, not for a team
```

- Token and roles: `apps/api/campaign_api/auth.py`. Row-level security: `apps/engine/ace_engine/row_security.py`.
- Each team also gets its own namespace, model config and token limit
  ([team-isolation.md](decisions/team-isolation.md), `agents/teams/`).
- Why one issuer URL serves the browser and the pods:
  [dex-issuer-on-cluster.md](decisions/dex-issuer-on-cluster.md).
