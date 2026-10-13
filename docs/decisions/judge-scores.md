# The judge scores every asset, and a low score stops the run

Status: accepted.

## Decision

- The judge is one agent step, `judge`, in the default workflow. It runs after the writers
  and the design agent and before the approval step. It is not an asset itself.
- It scores each asset from 1 to 5 against the rubric in
  `apps/engine/ace_engine/judge_rubric.md`, with one sentence of reason. The rubric is
  part of the judge's system prompt, so the AgentTemplate `ace-judge` and the role stay equal.
- The floor is 3 (`ace_engine.judge.FLOOR`). A score below it fails the run, and the failure
  reason names each asset, its score, and the judge's reason. A score at or above it never
  blocks. The owner can retry the step from the run view like any failed step.
- Each score is a run event: step is the asset, status is `scored`, and the reason is JSON
  with `score` and `reason`. No table or column is added: the run view (`scores` on the
  campaign) and the approval inbox (`score`, `score_reason` on each asset) read the latest
  `scored` event per asset.
- The publish step sends the last agent step before it, and the judge runs last, so publish
  skips the judge.

## Why

A run event needs no migration, already sits under row-level security, and shows in the event
stream. A floor in code is a plain rule a reviewer can read; the model only scores.
