# Proof the loop learns

Claim: campaign after campaign, the click rate goes up, and the gain goes away with
learnings off.

## How to run it

Five campaigns in a row, learnings on, then five with learnings off, at live depth on the
cluster against the simulated audience (the fake Marketo):

    ACE_API_TOKEN=<owner token> ACE_APPROVER_TOKEN=<approver token> ACE_DEPTH=live \
      uv run python -m evals.learning_curve --api-url <url> --campaigns 5 --out-dir learning-curve

It writes `learning-curve/trend.svg` (the trend chart), `results.md` (the tables below) and
`results.json`. `--learnings on|off` runs one side only. Click rate is clicks over opens.
How learnings are switched off: docs/decisions/learnings-off.md. When both sides run, the off side runs first so the on run's kept learnings
cannot reach its baseline.

The fast-depth run (scripted agent) proves the script works, not the claim: the scripted
agent writes the same email every time.

## Results

Owed to the end-of-batch live check. Numbers go here from that run.

### learnings on

| # | campaign | winner | opens | clicks | click rate |
|---|---|---|---|---|---|
| 1 | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD |
| 5 | TBD | TBD | TBD | TBD | TBD |

### learnings off

| # | campaign | winner | opens | clicks | click rate |
|---|---|---|---|---|---|
| 1 | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD |
| 5 | TBD | TBD | TBD | TBD | TBD |

Expected: the learnings-on rate rises from campaign 1 to 5; the learnings-off rate stays
flat within noise.
