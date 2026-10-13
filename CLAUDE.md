# agentic-campaign-engine

AI agents turn a threat report into a marketing campaign. Our Temporal engine
runs the pipeline. kagent 1.x runs the agents. The plan and every decision are
in `SPEC.md`. The spec, issue #18, holds the user stories, module design, and
test seams: read it before your first ticket.

## GitHub login

This machine's active `gh` account is a work account. Prefix every `gh`
command with `GH_TOKEN=$(gh auth token --user dackota)` and leave the active
account as it is.

## Issues

- **Tickets** are #19 to #63: label `ready-for-agent`, title prefix `S<n>:`.
  Tickets are the work.
- **Slices** #1 to #15 are parents that give a ticket its goal and context.
  A slice closes when all its tickets close.
- **Spec** #18 is reference. #16 is closed and replaced by #18.

Ask the user before you edit a slice, the spec, or a ticket's acceptance
criteria.

## Picking work

Work the frontier: open tickets with no open blockers.

```
GH_TOKEN=$(gh auth token --user dackota) gh issue list --repo dackota/agentic-campaign-engine --label ready-for-agent --search "-is:blocked"
```

A ticket is done when every acceptance criterion holds and its pull request,
with `Closes #<n>` in the body, merges.

## Tests

Every test drives one of the two seams in #18:

- the **Campaign API** (HTTP, the run event stream, webhooks), at fast depth
  with the scripted agent, or at live depth on the cluster
- the **browser**, with Playwright

Write the test first, at a seam. Row-level security is the only team filter,
so API tests prove the database rule too. Tests under `tests/tooling/` (repo
files and scripts) and `tests/spike/` (the cluster spikes) have no seam.

## Before you touch

- **Agents, tools, or publish steps**: read "The pipeline" rules in `SPEC.md`.
- **kagent, Substrate, OpenCode Go, or agentgateway facts**: start from
  `docs/sources.md`, then check the live page for the version pinned in
  `docs/pinned-versions.md`. kagent 1.x is alpha and ships a new release every
  few days.
