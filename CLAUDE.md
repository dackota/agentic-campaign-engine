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

Prove each thing at the **lowest test type** that can show it. Aim for about
70% unit, 20% component and API, 10% browser.

- **Unit**: pure logic, called directly. Python (`tests/engine/`) and web
  (`apps/web/src/*.test.ts`, vitest).
- **Component**: one React screen with fake data, in `apps/web/src/*.test.tsx`
  (vitest, jsdom, testing-library). Or one backend module with real Postgres.
- **Campaign API** (HTTP, the run event stream, webhooks), at fast depth with
  the scripted agent, or at live depth on the cluster. Use it only for what
  needs the wiring: auth, team isolation, durable runs, webhooks.
- **Browser**, with Playwright (`apps/web/e2e/`). Use it only for what a real
  browser and real stack can show: login, live status, painted previews, drag,
  layout.

Before you write a browser or API test, ask whether a unit or component test
can prove it. Write the test first. Row-level security is the only team
filter, so API tests prove the database rule too. Tests under `tests/tooling/`
(repo files and scripts) and `tests/spike/` (the cluster spikes) have no seam.

## Before you touch

- **Agents, tools, or publish steps**: read "The pipeline" rules in `SPEC.md`.
- **kagent, Substrate, OpenCode Go, or agentgateway facts**: start from
  `docs/sources.md`, then check the live page for the version pinned in
  `docs/pinned-versions.md`. kagent 1.x is alpha and ships a new release every
  few days.
