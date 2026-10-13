# The eval gate compares each run to a baseline in git

Status: accepted.

## Decision

- `evals/baseline.json` holds, per golden report, a `quality` score (the share of yes-or-no
  outcomes that went well: reached approval, key facts carried, hard checks passed) and a `judge`
  score (the judge's mean as a share of 5), plus the `margin` (0.05).
- `make evals` runs the golden set at fast depth and exits non-zero when any score falls more
  than the margin below its baseline, or a report is missing from the baseline. The report names
  each report, its score, the baseline, and which score dropped.
- The baseline changes only with `--update-baseline` (`make evals EVALS_ARGS=--update-baseline`).
  A normal run never writes it. The change shows in the diff for review.
- The runner turns the step cache on, so unchanged steps make no model call; the report prints
  how many agent steps were reused. `make evals` keeps its database in the Docker volume
  `ace-evals-cache`, so a rerun of unchanged steps (same input, same agent revision) makes no model
  call; `docker volume rm ace-evals-cache` starts cold.
- Judge agreement: `judge_labels.json` is a small set of assets a person labeled acceptable or
  not. Each run writes `judge_agreement.json` with the share where the judge's score is on the
  same side of the floor as the label. At fast depth the scripted judge scores everything 5, so the
  recorded rate reflects that; the live-depth rate is the one that says something about the rubric.
- No CI job yet. Once the repo is public (#63), add a job that runs `make evals` on every PR.

## Why

A fixed file in git makes "worse" a diff a reviewer can see, and an explicit update keeps a
regression from being absorbed silently. Fast depth with the scripted agent proves the gate's
mechanics; live depth measures the model.
