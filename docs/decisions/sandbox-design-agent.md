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

The Agent runs on the Go harness; whether it can call `sandbox exec` itself as a tool is
unproven in alpha9. If it cannot, the engine's live step runs the program the agent wrote in
the sandbox and reads the cards from stdout; the contract and the saving do not change.
