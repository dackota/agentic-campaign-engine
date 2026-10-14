# Decision: a step cache keyed by step type, agent revision digest and input hash (S11)

Date: 2026-10-12. Status: accepted.

## Decision

An agent step that runs again with the same step type, the same agent revision and the same
input reuses its saved output and makes no model call. The key is exactly those three parts
(`ace_engine/step_cache.py`):

- **Step type**: the role's template name (`ace-email-writer`, `ace-research`, ...).
- **Agent revision digest**: the SHA-256 of the agent's card digest, read from
  `<agent url>/.well-known/agent-card.json` before the step. A step with a brand reviewer
  also reads the reviewer's card, and the stored digest is the SHA-256 of the card digests
  joined together. A card that cannot be read means no cache for that step.
- **Input hash**: the SHA-256 of the report, the outputs of the steps before it, and the
  step's review rounds, as canonical JSON.

A hit is booked in the cost ledger at zero tokens and zero cost under the model of the saved
run, with `cache_hit: true` on the step in the campaign's `cost.steps`.

## Choices the ticket left open

- **Opt in per campaign** (`use_step_cache` on `POST /campaigns`, default false). A shared
  cache would turn two runs of one report into one, which would hide the second run's cost,
  review and failures from anyone who expects a fresh run. It is also why the existing
  suite, where tests share one report, needs no change.
- **Per team.** The spec scopes data by team. Entries carry the team, and a lookup names
  it, so one team never reads another's output. The key stays the three parts.
- **The revision digest is the agent card.** kagent serves one for each Agent. Whether a
  change to an Agent's prompt or model changes the card is not settled for kagent 1.0 alpha;
  the digest follows what the controller serves. The replacement is the Agent's generation
  or a hash of its resolved spec, once the engine can read it.
- **Flagged output is not saved.** An output the brand reviewer still flags is left for a
  human, and a later run must review it again.
- **Failures are not saved.** Only a step that succeeded writes an entry.
- Entries do not expire. The digest changes with the agent, and an input change changes the
  hash.

## Consequences

- New columns: `campaigns.use_step_cache`, `step_usage.cache_hit`, and the table
  `step_cache`. `Base.metadata.create_all` adds the table to a live database but not the
  columns (#84); they are additive `ADD COLUMN IF NOT EXISTS ... DEFAULT false`.
  Each start now adds them ([additive-schema-at-start.md](additive-schema-at-start.md)).
- The cache is in the same Postgres as the ledger; there is no second store to run.
