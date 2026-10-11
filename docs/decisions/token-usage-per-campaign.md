# Decision: token use ties to a campaign through A2A usage data (S11)

Date: 2026-10-11. Status: accepted.

## Decision

The engine reads token use off each agent's A2A task reply, at `result.metadata.usage`
(`model`, `input_tokens`, `output_tokens`; OpenAI-style `prompt_tokens` and
`completion_tokens` are read too). The Agent invoker adds up every call of a step, the
repair attempt included. The worker books the sum against the step in the cost ledger
(`step_usage`), priced by `ace_engine/cost.py`. Trace context is not used for cost.

## Why A2A usage data

- The engine already knows which step and campaign every A2A call is for: each step has
  its own session and idempotency key. Usage that comes back on the reply needs no
  lookup to tie it to a step.
- The budget check runs before each model step, inside the workflow. It needs the spend
  at that moment. A2A usage is in the ledger as soon as the step ends. Trace data reaches
  the engine only after the collector exports it and the engine queries the trace store,
  which adds a store, a delay, and a failure mode to every step.
- It works at fast depth. The scripted agent puts usage on its replies, so seam 1 tests
  check exact numbers with no collector running.
- Traces stay what S12 (#57) uses them for: seeing where time and money went. They can
  carry the same numbers as span attributes without being the source of truth.

## Why not trace context

Passing trace context through kagent to the gateway, then reading token counts back from
the gateway's spans, would tie usage to a campaign even for calls the engine does not
see. But the engine makes every model call through an agent step, so there are none.
The cost is a running collector and trace store on the budget's critical path.

## Consequences

- A reply with no usage, or malformed usage, is booked at zero tokens under the model
  `unreported`, and the worker logs a warning. A budget cannot stop spend it is not told
  about, so the live transport must keep usage on the reply.
- The live depth A2A client (kagent 1.x serves gRPC, see `docs/sources.md`) must map
  kagent's own usage fields onto `metadata.usage`. Check the field names on the live
  reply when that client lands.
- Every model is priced at the default list price ($3 in, $15 out per million tokens)
  until the price table names it. OpenCode Go is a flat monthly rate; booking it at a
  list price makes the budget a cap on use, not a copy of the bill.
- A budget is checked before each model step, not during one. Writers that start
  together all run, so a run can end a wave above its budget by up to one wave of steps.
