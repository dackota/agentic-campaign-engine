# Decision: teams are kept apart by row-level security and by namespace (S6)

Date: 2026-10-12. Status: accepted.

## Decision

**Data.** Every table but `workflow_versions` and `alerts` holds one team's rows and has row-level
security on, with one policy (`apps/engine/ace_engine/row_security.py`). `campaigns`
shows a row when its `team` equals the session setting `ace.team`. Every other team table
shows a row when its campaign is one the team can see. The API runs each signed-in
request as the `ace_team` role (`SET LOCAL ROLE`) with `ace.team` set to the user's team
from the token, so no API query names a team. A session with no team set sees nothing.

**The step cache.** `step_cache` has its own `team` column (a saved output is reused
only inside its team), so its policy is `team = current_setting('ace.team')` like
`campaigns`. The worker reads and writes the cache through `for_team` with the campaign's
team, and the cache's queries name no team. The worker installs the role and policies at
start too, since it may start before the API.

**SQL.** DDL identifiers (schema, table, column, policy, and role names) cannot be bound parameters, so
`row_security` quotes each one through the dialect's identifier preparer; the team itself
is always a bound parameter to `set_config`.

**Who is not filtered.** The worker and the signed webhooks connect as the tables' owner,
which row-level security does not filter. They act for the system: the worker runs one
campaign by id, and a webhook is signed by the marketing system, which serves every team.
The trace middleware reads a campaign's `traceparent` as the request's team for a campaign
path, and as the system only for a webhook whose signature verifies.

**Workflows are shared.** A saved workflow is a DAG of steps, not a team's data. Every
team can list, read, run, and save a new version of any workflow name, so
`workflow_versions` has no policy. A run already in flight keeps the version it pinned;
only later runs that name the workflow pick up a new version. `alerts` are the platform's
own (Grafana alerts shown to every signed-in user as a banner), so they have no policy
either. The write is accepted; see "Accepted after review".

**Agents.** Each team runs the role Agents in its own namespace `team-<team>`
(`agents/teams/<team>`), on its own WorkerPool and harness, and every role template uses
the team's own ModelConfig `<team>-model`. That ModelConfig calls the model through the
team's own gateway route `/<team>/v1`, which has the team's own token limit
(`agents/teams/gateway.yaml`). At live depth the worker sends a step to the Agent in the
namespace of the campaign's team. A team that is not a namespace name is refused.

## Why row-level security, not a team condition in code

- One rule in the database covers every query, including the ones written later. A
  forgotten `WHERE team = ...` cannot leak a row.
- A team B request for a team A campaign finds no row, so every route answers 404 through
  the same missing-campaign check, and nothing tells B the campaign exists.
- Tests prove the database rule itself: they read the tables as the team role.

## Why `SET LOCAL ROLE`, not a login per team

The tables' owner, and a superuser, skip row-level security. A per-transaction
`SET LOCAL ROLE ace_team` plus `set_config('ace.team', ..., true)` drops to a role the
policies apply to, on the API's one pool, and both reset when the transaction ends, so a
pooled connection never carries a team into the next request.

## Not done

- **Learnings** have no table yet. When they get one, it is a team table and gets the
  same policy.

## Accepted after review (#89)

Date: 2026-10-13. The #40 security review left three MEDIUM findings.

- **Shared workflows are writable by every team. Accepted.** Any owner of any team may save
  a new version of any workflow name. A run in flight keeps its pinned version, so the
  change reaches only later runs. A workflow is a DAG of steps, not a team's data, and the
  cluster has two demo teams. What would close it: an owning team per workflow name (the
  team of the first save), with row-level security letting a team add a version only of a
  name it owns, and the default workflow owned by the platform.
- **Webhooks and the trace middleware acted as the owner with no team scope.**
  - *Trace middleware: fixed.* A `/campaigns/{id}` request joins the campaign's trace only
    when its token verifies and its team can read the campaign's `traceparent` through
    row-level security (the bearer header, or the `access_token` query). A webhook joins
    only when its body's signature verifies with its sender's secret. Anything else starts
    a trace of its own. The middleware never answers a request or changes a status: the
    route decides. A read is cached per campaign and per reader, so one team's read is
    never served to another.
  - *Webhooks: accepted.* Marketo and Workfront each sign with one secret for the whole
    company, and their payloads carry no team. A signed webhook speaks for the whole
    marketing system, so it writes as the owner for any team's campaign. What would close
    it: one secret per team, with the API checking the signing team against the campaign's
    team.
- **The team namespaces and gateway routes are a budget boundary, not a security
  boundary. Accepted.** They split Agents and token budgets. There is no NetworkPolicy,
  ResourceQuota, or RBAC per team namespace, and a route is picked by its URL path, so a
  pod that can reach the gateway can spend another team's budget. The cluster is one
  laptop with two demo teams, and SPEC.md puts a production security review out of scope.
  What would close it, for production: a default-deny NetworkPolicy per team namespace,
  with allows for the gateway, the MCP servers, kagent, and Substrate, and a gateway
  policy that ties each `/<team>/v1` route to its namespace.

## Not done

- **Learnings** have no table yet. When they get one, it is a team table and gets the
  same policy.
