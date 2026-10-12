# Decision: the eval hard checks are deterministic code (S10, #53)

Date: 2026-10-12. Status: accepted.

Decision: **the eval runner grades assets with plain Python checks (`evals/checks.py`),
not with the brand reviewer's model run.**

## Why

- Same asset, same verdict. A model run can pass an asset on one run and fail it on the
  next, so a change in the report could be noise. The eval exists to show whether the
  pipeline got better or worse; a grader that drifts hides that.
- The eval needs no model, key, or gateway to grade. It runs at fast depth in tests with
  the scripted agent, and at live depth the only model calls are the ones the pipeline
  itself makes.
- A planted bad asset must show as failed every time. Only a deterministic check can
  promise that.
- Free to run on every asset of every golden report.

## How it relates to the brand reviewer

`apps/engine/ace_engine/brand_review.py` is the pipeline's own gate: a model reads the
drafts and flags problems before a person approves. The hard checks mirror its four
checks (uncited fact, banned claim, off-brand word, length) as regexes and limits, so the
eval measures the same rules without depending on the reviewer. The two are separate
code: the reviewer may judge more than the regexes catch, and the hard checks may flag
what the reviewer let through. A gap between them is a finding for the report, not a bug
in either. If the brand rules change, change both.

## Cost

The regexes catch the listed phrases only; they miss a new off-brand word until someone
adds it. Tone and factual accuracy beyond the key-fact match stay with the human reader
of the report.
