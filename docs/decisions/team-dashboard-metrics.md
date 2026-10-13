# The team dashboard: how quality and click rate are worked out

Status: accepted.

## Decision

- Quality score of a campaign is the mean of the judge's latest score for each of its assets
  (see `judge-scores.md`). A campaign the judge has not scored has none (null).
- Click rate of a campaign is clicks divided by opens, over both A/B variants together. A
  campaign with no opens has none (null).
- The team totals use the same rules over all the team's scores and activities, not a mean of
  the per-campaign means.
- Cost is the sum of the cost ledger rows, in dollars.
- The dashboard lists campaigns oldest first; the list is the trend. No table or column is
  added: it reads the run events, the cost ledger, and the activities, all under row-level
  security.

## Why

The marketing system reports opens and clicks but no send count, so a rate per send cannot be
worked out; clicks per open is the rate the data supports. Null, not zero, says "nothing to
divide yet", so a campaign with no data is not read as a bad one.
