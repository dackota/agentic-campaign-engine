# Decision: Python BYO agent for S13 (S0 spike, #22)

Date: 2026-10-10. Status: accepted. Replaces the "S13: no, for now" note in `k3d-or-kind.md`.

Result: crashed (the stock Python BYO never wakes; with a fast readiness endpoint it survives).

Decision: **go**, on the condition below. Python BYO agents are allowed for S13.

## Evidence

Details in `docs/spike-log.md`, section 14. Pinned `kagent-adk` digest, `byo: {}`,
`KAGENT_PORT=80`, readiness on 8081.

- It answers a message (`42`), and the golden snapshot restores in 0.1 s.
- After a suspend, the stock agent never wakes: Substrate's wake-up probe (about 5 s) is
  cancelled before the Python imports finish, and it retries forever. Draft bug 6.
- With `/readyz` answering before the heavy imports, the agent woke twice, in 0.4 s.
- No `Illegal instruction` appeared on arm64 k3d. That crash may still show on other CPUs;
  recheck on the real target.

## Conditions for S13

1. The agent must answer `/readyz` within about 1 s of process start, before importing
   kagent-adk and google-adk. Copy the early-readiness block in
   `manifests/spike/python-byo-early-readyz.yaml`.
2. A wake is a cold start: process memory is lost (boot id and counter reset). Keep state in
   files or in the Campaign API, never in memory.
3. S13 must include a suspend and wake test on its own agent, as `scripts/spike/python-wakeup.sh` does.
4. If the early-readiness block proves too fragile, S13 falls back to the Go harness.
