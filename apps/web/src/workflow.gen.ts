// Generated from apps/engine/ace_engine/workflow.schema.json by
// scripts/gen_workflow_types.py. Do not edit: run `make types`.

export const StepKindValues = ["agent", "render", "approval", "publish", "wait"] as const;
/** What a step does: call an agent, render an asset, wait for a human, publish, or wait a while. */
export type StepKind = (typeof StepKindValues)[number];

/** Lower-case letters, digits, and underscores, starting with a letter. */
export type StepId = string;

/** How a failing step is retried before it stops the run. */
export interface RetryPolicy {
  /** How many times the step runs before it gives up, the first attempt included. */
  maximum_attempts?: number;
  /** How long to wait before the first retry; each later wait doubles. */
  initial_interval_seconds?: number;
}

export interface WorkflowStep {
  id: StepId;
  kind: StepKind;
  /** How long a wait step waits. Only wait steps have it, and they must. */
  duration_seconds?: number;
  /** How long one attempt of the step may run before it counts as failed. */
  timeout_seconds?: number;
  retry?: RetryPolicy;
  /** How many times the step runs before the run fails. Defaults to the step kind's own limit. */
  max_attempts?: number;
  /** How many review rounds the step may loop through before it stops. Zero means no review loop. */
  review_rounds?: number;
}

/** The step `to` starts only after the step `from` has succeeded. */
export interface WorkflowEdge {
  from: StepId;
  to: StepId;
}

/** A campaign workflow: a DAG of steps joined by edges. The one source of truth for workflow shape; the web app's TypeScript types are generated from it. */
export interface Workflow {
  steps: WorkflowStep[];
  edges: WorkflowEdge[];
}
