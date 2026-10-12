# Decision: teams are kept apart by row-level security and by namespace (S6)

Date: 2026-10-12. Status: accepted.

## Decision

**Data.** Every table but `workflow_versions` holds one team's rows and has row-level
security on, with one policy (`apps/engine/ace_engine/row_security.py`). `campaigns`
shows a row when its `team` equals the session setting `ace.team`. Every other team table
shows a row when its campaign is one the team can see. The API runs each signed-in
request as the `ace_team` role (`SET LOCAL ROLE`) with `ace.team` set to the user's team
from the token, so no API query names a team. A session with no team set sees nothing.

**Who is not filtered.** The worker and the signed webhooks connect as the tables' owner,
which row-level security does not filter. They act for the system: the worker runs one
campaign by id, and a webhook is signed by the marketing system, not sent by a team.

**Workflows are shared.** A saved workflow is a DAG of steps, not a team's data. Every
team can run any saved workflow, so `workflow_versions` has no policy.

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
- The trace middleware reads a campaign's `traceparent` before sign-in, as the owner. A
  team B request for a team A campaign id still gets a 404, but its span joins team A's
  trace. Only the trace store sees that.
- The team namespaces and gateway routes split Agents and token budgets; they are not a
  security boundary. There is no NetworkPolicy, ResourceQuota, or RBAC per team
  namespace, and a route is picked by its URL path, so a pod that can reach the gateway
  can spend another team's budget. A default-deny NetworkPolicy per namespace and a
  gateway policy that ties each route to its namespace would close that.
