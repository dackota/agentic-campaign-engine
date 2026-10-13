# Decisions

The planning table in [SPEC.md](../../SPEC.md) ("Decisions") has 19 rows, all decided on
2026-10-09. This index maps each row to the ADR that covers it. A row with no ADR was a
planning choice with no trade-off worth a record; its row in SPEC.md is the record.

| # | Topic | Where it is recorded |
|---|---|---|
| 1 | Story | No ADR. [SPEC.md](../../SPEC.md) "What this is" |
| 2 | Deliverable | No ADR. The [README](../../README.md) proof table is the deliverable |
| 3 | Timeline | No ADR. [SPEC.md](../../SPEC.md) "Slices" |
| 4 | Orchestration | [temporal-dag-engine.md](temporal-dag-engine.md), [step-cache.md](step-cache.md), [team-step-limit.md](team-step-limit.md) |
| 5 | k3d risk | [k3d-or-kind.md](k3d-or-kind.md) |
| 6 | Model | [llm-gateway-failover.md](llm-gateway-failover.md), [prompt-caching.md](prompt-caching.md) |
| 7 | Agents | [python-byo-wakeup.md](python-byo-wakeup.md), [sandbox-design-agent.md](sandbox-design-agent.md) |
| 8 | Integrations | [mcp-servers.md](mcp-servers.md), [cms-and-asset-store.md](cms-and-asset-store.md) |
| 9 | App stack | No ADR. Each part's job is in [architecture.md](../architecture.md) |
| 10 | Auth | [team-isolation.md](team-isolation.md), [dex-issuer-on-cluster.md](dex-issuer-on-cluster.md) |
| 11 | Rendering | [pdf-with-reportlab.md](pdf-with-reportlab.md), [sandbox-design-agent.md](sandbox-design-agent.md) |
| 12 | Analytics | [learnings-store.md](learnings-store.md), [learnings-off.md](learnings-off.md), [ab-result-stats-check.md](ab-result-stats-check.md), [team-dashboard-metrics.md](team-dashboard-metrics.md) |
| 13 | Evals | [eval-gate.md](eval-gate.md), [hard-checks-are-code.md](hard-checks-are-code.md), [judge-scores.md](judge-scores.md) |
| 14 | Resources | [make-up-own-cluster.md](make-up-own-cluster.md); the memory numbers are in the [README](../../README.md) "Docker memory" |
| 15 | Deploy | [helm-tilt-ghcr-digest-pins.md](helm-tilt-ghcr-digest-pins.md) |
| 16 | Order | No ADR. [SPEC.md](../../SPEC.md) "Slices" |
| 17 | Repo | No ADR. Private until the ship slice; #63 decides the public step |
| 18 | Plan home | No ADR. The spec and one GitHub issue per slice |
| 19 | Test seams | No ADR. [README](../../README.md) "Tests" |

## Decisions made while building

These came out of slices, not the planning table.

| ADR | Decision |
|---|---|
| [asset-approval.md](asset-approval.md) | Each asset is approved on its own |
| [dashboards-and-alerts.md](dashboards-and-alerts.md) | Dashboards and alerts are files; a webhook shows them in the app |
| [one-trace-per-campaign.md](one-trace-per-campaign.md) | One trace follows a campaign from start to publish |
| [token-usage-per-campaign.md](token-usage-per-campaign.md) | Token use ties to a campaign through A2A usage data |
