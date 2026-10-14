# Decision: our own DAG engine on Temporal; each agent step calls a kagent Agent over A2A

Status: accepted. Decided in planning (SPEC.md Decisions, row 4).

## Decision

The campaign pipeline is a Temporal workflow that follows a workflow DAG stored with the run.
Each step of the DAG is an activity. An agent step asks one kagent Agent over A2A and gets
back JSON that fits a schema. kagent runs the agents; it does not run the pipeline.

- `apps/engine/ace_engine/dag.py` holds the pure graph rules (order, ready steps, cycle
  check). `apps/engine/ace_engine/workflow.schema.json` is the shape of a DAG.
- `apps/worker/campaign_worker/workflow.py` starts every ready step of a wave at the same
  time, takes each step's timeout and retry policy from the DAG, waits for approval and
  retry signals, and lets the owner raise a spent budget.
- `apps/engine/ace_engine/invoker.py` makes the A2A call, checks the reply against the
  step's schema, and allows one repair try.

## Why

The engine needs an orchestration layer: multi-agent pipelines, state, error recovery, and
parallel runs. kagent 1.x has agents but no pipeline engine. Temporal gives durable state,
retries, signals and resume after a crash without us writing them. The workflow is a thin
shell; the rules live in plain Python that tests can drive without Temporal.

## Trade-offs

- We own the DAG format and its checks, so the workflow builder in the web app and the API
  must agree on one JSON Schema (`make types` generates the web types from it).
- Temporal runs as the dev server with a SQLite file on a volume. That is enough for a
  laptop and not a production setup.

## Proof

`tests/api/test_workflow_runs.py`, `tests/api/test_step_failures.py`,
`tests/api/test_workflow_property.py`.
