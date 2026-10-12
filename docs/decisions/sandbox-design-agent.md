# The design agent runs in a standalone sandbox that reaches nothing

Decision (S7, ticket 43): the design agent writes a program that draws two social cards and
runs it in a kagent standalone sandbox. The agent only makes the cards. The engine saves
them to the asset library (`cards/<campaign>/<name>` in the asset bucket) once the step
returns, so the sandbox needs no credentials and no route to the library.

## What the sandbox may reach

Nothing. `docs/spike-log.md` section 16 measured the alpha9 sandbox: egress is
deny-by-default through Substrate's proxy (every HTTP host answers 403, including in-cluster
services and the metadata address), nothing reaches it from outside except `kagent sandbox
exec/upload/download`, and the SandboxTemplate CRD has no egress field to widen (draft bug
6). The program therefore uses no package, font, or API; it draws SVG from text. The
template `ace-design-sandbox` (agents/templates.yaml) is the spike template pinned by digest
with no `env`, so no secret can enter it.

## Proof

`scripts/design-sandbox.sh` creates a sandbox from `ace-design-sandbox` on `k3d-ace`, runs
the card program, reads two SVGs back, shows that a host it does not need
(`example.com`) is not reachable from inside, and deletes the sandbox.

## Contract and fast depth

`design_cards.schema.json`: exactly two cards, each a safe file name and an SVG with no
script, event handler, `javascript:` link, or `foreignObject`. At fast depth the scripted
agent returns the same two cards for every report.

## Open

Where the code runs: the Agent runs on the Go harness, and whether it can call `sandbox exec`
as a tool is unproven in alpha9, so the AgentTemplate has no sandbox tool. The built path is
the fallback: at live depth the agent replies with `program` (a shell script), the engine's
`run_agent_step` runs it in a new `ace-design-sandbox` through the `kagent sandbox` CLI
(`campaign_worker/sandbox.py`, API URL from `ACE_KAGENT_API_URL`, else the agent URL), reads
the two `CARD <n> <base64>` lines from stdout, checks them against the contract, and deletes
the sandbox on every exit. The saving does not change. At fast depth the scripted agent
replies with the cards directly.

Not re-checked live: the sandbox facts above come from the alpha9 spike (`docs/spike-log.md`
section 16, recorded in `docs/sources.md` on 2026-10-12), not from the live kagent pages or a
running cluster. The live run of `scripts/design-sandbox.sh` and of a live design step is
owed.
