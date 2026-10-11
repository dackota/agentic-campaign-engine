# Decision: how the A/B test calls a winner (S9, #48)

Date: 2026-10-11. Status: accepted.

Decision: **a normal-approximation test on the open counts** (the small-rate form of the
two-proportion z-test), not a Bayesian win rate.

## The check

- The measure is the open rate of each variant. The A/B send splits the audience evenly,
  so both variants have the same number of sends n. The Campaign API keeps opens and
  clicks but no send count. The pooled two-proportion z-test is
  `z = (a - b) / sqrt((a + b) * (1 - p))`, with `p = (a + b) / 2n` the pooled open rate.
  We drop the `(1 - p)` factor and use `z = (a - b) / sqrt(a + b)`: the small-rate
  approximation, which treats the opens as Poisson counts. It is valid when the open
  rate is low, and it understates z (so understates confidence) as the rate grows: at a
  50% pooled rate z is too low by a factor of about 1.4. That errs toward "no decision
  yet", never toward a false win, so it is accepted for this demo, on top of the 95% bar
  and the 30-open floor. Store the send count and use the pooled form if
  the rate ever runs high. Clicks are too few to test on their own (about 10 per
  variant for the 120-reader audience).
- Two-sided. Confidence is `1 - p`, from `math.erf`.
- A winner needs both: at least 30 opens in total, and confidence of at least 95%. The
  winner is the variant with more opens.
- Otherwise the result is "no decision yet", with no winner. A tie, or a missing
  variant, is also "no decision yet".

## Why not a Bayesian win rate

- It needs a prior and a "probability to beat" cut-off. Both are choices a reader must
  take on trust, and the number shown ("93% to beat A") is easy to misread.
- The z-test is a closed form with the standard library (`math.erf`): no sampling, no
  dependency, same answer on every run. A property test can state its contract
  exactly.
- The demo's sample is small, and a fixed minimum sample plus a fixed confidence bar is
  the plainest way to refuse an early call. The 30-open floor also keeps the normal
  approximation reasonable.

## Cost

The test says nothing after a peek that changes the plan: reading it early and often
raises the false-win rate. The app only reads it; nobody stops the test on a win.
