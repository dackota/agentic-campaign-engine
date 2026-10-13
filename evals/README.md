# evals

The golden set and the eval runner.

- `golden.json`: about 10 made-up threat reports, each with the key facts a campaign must carry.
- `checks.py`: the hard checks (uncited_fact, banned_claim, off_brand_word, length), run on every asset.
- `runner.py`: drives the Campaign API with each report and writes a readable report.

Run it against a running API (at live depth on k3d-ace, or the fast-depth stack):

    ACE_API_TOKEN=<a signed-in user's token> uv run python -m evals --api-url <url> --out report.txt

The depth is whatever the API runs at; set `ACE_DEPTH=live` so the runner waits long enough
for real model replies. The exit code is 1 when any report fails.

<<<<<<< HEAD
## Learning curve

`learning_curve.py` runs campaigns in a row, approves each, lets the simulated audience open
and click, and charts click rate by campaign. By default it runs twice, learnings on and
learnings off, and writes `trend.svg`, `results.md` and `results.json`. See
`docs/learning-proof.md`.

    ACE_API_TOKEN=<owner token> ACE_APPROVER_TOKEN=<approver token> ACE_DEPTH=live \
      uv run python -m evals.learning_curve --api-url <url> --campaigns 5 --out-dir learning-curve
=======
## The gate

`make evals` starts the fast-depth stack (needs only Docker), runs the golden set, and compares
each report to `baseline.json`. A drop in a report's quality or judge score past the margin
(`margin` in the baseline file) fails with a readable report, and so does a report missing from
the baseline. The step cache is on, so a step whose input and agent revision are unchanged makes
no model call; the report counts the reused steps.

The baseline changes only on purpose: `make evals EVALS_ARGS=--update-baseline` rewrites it from
the run, and the diff goes through review. Each run also rewrites `judge_agreement.json`: how often
the judge's score lands on the same side of the floor as the hand labels in `judge_labels.json`.
At live depth, run the runner by hand with `--baseline evals/baseline.json`.

CI runs this gate on every PR once the repo is public (#63); private runners are too small for
the stack. See `docs/decisions/eval-gate.md`.
>>>>>>> land/ace
