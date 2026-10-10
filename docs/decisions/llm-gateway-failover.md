# Decision: agentgateway with OpenCode Go first and Anthropic second (S1)

Date: 2026-10-10. Status: accepted.

## Decision

Every agent model call goes through agentgateway. One backend holds two priority
groups: OpenCode Go first, then a pay-as-you-go Anthropic API key. Each team gets its
own ModelConfig and gateway route with a token budget. A Claude subscription login is
never the backup.

## Why agentgateway

- kagent 1.x documents it as a model provider: a ModelConfig with provider `OpenAI` and
  `baseUrl` at the gateway (`docs/sources.md`). So agents need no key and no code change.
- The gateway holds every provider key. No agent pod holds one
  (`scripts/spike/gateway-check.sh` checks this).
- Priority groups, health-based eviction and retries are all config, not code. It turns
  OpenAI-style requests into Anthropic Messages calls, so both styles fit in one list
  (`docs/spike-log.md` section 18).
- It does per-route token budgets and logs tokens per call. With the `x-team` attribute,
  the log shows tokens per team.

## Why this failover order

1. **OpenCode Go** costs $10 a month at a flat rate. It is the cheap default for a demo
   that runs many agent calls.
2. **Anthropic API, pay as you go**, is second. It costs per token, so it only carries
   traffic while OpenCode Go is down, rejects the key (401/403) or fails (5xx). It is a
   different company with different outages, so one failure does not take out both.

A 429 is left out of the eviction rule. The gateway's own per-team limit answers 429,
and agentgateway counts that against the backend. With 429 in the rule, one team over
budget moved every team to the paid key. Until the user adds a key, group 2 is the
in-cluster mock's Anthropic-style route.

## Why a Claude login cannot be the backup

A Claude subscription login (Claude.ai Pro or Max, or the Claude Code login) is an OAuth
session for one person's interactive use. It is not an API key. A gateway cannot hold it
as a server credential, and it cannot share it across many agents. The subscription is
for one person's use, not for serving other software (SPEC.md decision 6: "A Claude login
cannot sit behind a gateway"). The backup must be an API key from the Anthropic Console,
billed per token.

## Consequences

- The real Anthropic run is owed after the merge (`docs/spike-log.md` section 18).
- An OpenCode Go quota 429 fails over more slowly than a bad key, since it only lowers
  health. Revisit if OpenCode starts throttling.
- Team budgets are spike numbers (10000 tokens a minute). S6 sets the real ones.
- The two-group backend is written three times: `manifests/spike/gateway.yaml` (group 2
  is the mock), `gateway-anthropic.yaml` (group 2 is the real API) and
  `gateway-failover-test.yaml` (group 1 has a fake key). A change to group 1 must go into
  all three. The team blocks in `gateway.yaml` differ only by name. For a spike with two
  teams, plain copies read more easily than a generator. S6 adds teams and should template them.
