import assert from "node:assert/strict";
import { test } from "node:test";
import { problemsOf } from "./builderMessages.ts";
import type { WorkflowStep } from "./workflow.gen.ts";

const steps: WorkflowStep[] = [
  { id: "email_draft", kind: "agent" },
  { id: "publish", kind: "publish" },
];
const one = (rule: string, message: string, on: WorkflowStep[] = steps) => {
  const problems = problemsOf(on, [{ rule, message }]);
  assert.equal(problems.length, 1);
  return problems[0]!;
};
// A plain-word message names no schema text, quotes, or ids.
const assertPlain = (text: string) => assert.doesNotMatch(text, /["[\]{}_]|\bsteps\.\d|\bschema\b/);

test("too_large says the workflow is too big", () => {
  const p = one("too_large", "the workflow is over 100000 bytes");
  assert.equal(p.stepId, null);
  assert.match(p.text, /too big/);
  assertPlain(p.text);
});

test("not_json says the workflow could not be read", () => {
  const p = one("not_json", "the workflow is not valid JSON");
  assert.match(p.text, /could not be read/);
  assertPlain(p.text);
});

test("unknown_step_kind lands on the step", () => {
  const p = one("unknown_step_kind", "steps.1.kind: 'zap' is not a step kind; use one of agent, render");
  assert.equal(p.stepId, "publish");
  assert.match(p.text, /type the builder does not know/);
  assertPlain(p.text);
});

test("invalid_shape on an empty step list asks for a step", () => {
  const p = one("invalid_shape", "steps: [] should be non-empty", []);
  assert.equal(p.stepId, null);
  assert.equal(p.text, "Add at least one step");
});

test("invalid_shape on a step setting lands on that step", () => {
  const p = one("invalid_shape", "steps.0.max_attempts: 0 is less than the minimum of 1");
  assert.equal(p.stepId, "email_draft");
  assert.match(p.text, /settings/);
  assertPlain(p.text);
});

test("invalid_shape elsewhere gets a general plain message", () => {
  const p = one("invalid_shape", "workflow: 'steps' is a required property");
  assert.equal(p.stepId, null);
  assertPlain(p.text);
});

test("duplicate_step_id lands on the repeated step", () => {
  const dup: WorkflowStep[] = [...steps, { id: "publish", kind: "publish" }];
  const p = one("duplicate_step_id", "two steps are named 'publish'", dup);
  assert.equal(p.stepId, "publish");
  assert.match(p.text, /share a name/);
  assertPlain(p.text);
});

test("dangling_edge says a connection points nowhere", () => {
  const p = one("dangling_edge", "the edge 'a' -> 'b' names a step that does not exist");
  assert.equal(p.stepId, null);
  assert.match(p.text, /connection/);
  assertPlain(p.text);
});

test("cycle says the steps loop back", () => {
  const p = one("cycle", "the steps loop back on themselves; a workflow must not return");
  assert.match(p.text, /loop back/);
  assertPlain(p.text);
});

test("publish_without_approval lands on the publish step", () => {
  const p = one("publish_without_approval", "publish step 'publish' needs an approval step before it, so nothing");
  assert.equal(p.stepId, "publish");
  assert.match(p.text, /needs an approval step before it/);
  assertPlain(p.text);
});

test("publish_without_content lands on the publish step", () => {
  const p = one("publish_without_content", "publish step 'publish' needs an agent step before it to write");
  assert.equal(p.stepId, "publish");
  assert.match(p.text, /needs an AI step before it/);
  assertPlain(p.text);
});

test("an approval step first is flagged on that step, with no API rejection", () => {
  const first: WorkflowStep[] = [{ id: "approval", kind: "approval" }, ...steps];
  const problems = problemsOf(first, []);
  assert.deepEqual(problems, [{ stepId: "approval", text: "An approval step needs a step before it" }]);
});

test("a valid workflow has no problems", () => {
  assert.deepEqual(problemsOf(steps, []), []);
});
