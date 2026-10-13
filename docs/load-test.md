# Load test: 20 campaigns at once

The load script (`tests/harness/load.py`) starts N campaigns at once through the Campaign
API on the default workflow, with the step cache on and one report for every campaign. It
waits until each run's drafting ends (waiting for approval, or failed) and writes:

- `cost_per_campaign_usd`: the mean of each campaign's `cost.cost_usd`
- `p50_seconds`, `p95_seconds`: nearest-rank run time from create to the end of drafting,
  over the runs that finished
- `cache_hit_rate`: agent steps served from the step cache over all agent steps
- `lost`: runs that did not end waiting for approval: failed runs, runs that missed the
  deadline, and runs whose calls failed or got a reply the script could not read
- `replies_429`: the Campaign API's 429 replies, plus runs a model 429 stopped (a failure
  reason that holds the gateway's `429 Too Many Requests`; not yet seen live, see
  docs/sources.md)
- `lost_reasons`: why each lost run was lost: its failure reason, or the deadline it missed

Each team runs at most `ACE_TEAM_STEP_LIMIT` model-calling steps at once (default 8,
docs/decisions/team-step-limit.md), so 20 campaigns of one team queue for the model instead
of storming it.

## Fast depth

Checked by `tests/api/test_load_script.py` on every test run (20 campaigns, scripted agent):

```
make load LOAD_ARGS="--campaigns 20 --out load-fast.json"
```

## Live depth (owed: end-of-batch live check)

Needs the `k3d-ace` cluster up (`make up`). The harness forwards the kagent controller and
the model calls go through agentgateway. Exact command:

```
ACE_DEPTH=live make load LOAD_ARGS="--campaigns 20 --out load-live.json"
```

Gateway 429s that a step retried and got past do not stop a run, so count them from the
gateway proxy's access log for the same window. The status field is `http.status`
(docs/sources.md):

```
kubectl --context k3d-ace logs -n agentgateway-system deployments/agentgateway-proxy --since=1h | grep -c 'http.status=429'
```

| Number | Live result |
| --- | --- |
| Date, commit | _TBD_ |
| Campaigns | 20 |
| Finished / lost | _TBD_ / _TBD_ |
| Cost per campaign (USD) | _TBD_ |
| p50 run time (s) | _TBD_ |
| p95 run time (s) | _TBD_ |
| Cache hit rate | _TBD_ |
| 429 replies (script) | _TBD_ |
| 429s at the gateway (log) | _TBD_ |

Pass: 0 lost, and no 429 storm (gateway 429s a small share of the model calls, and none
that stopped a run).
