import assert from "node:assert/strict";
import { test } from "node:test";
import { graphLayout, summarizeSteps } from "./runGraph.ts";

const steps = ["brief", "a", "b", "join"].map((id) => ({ id, kind: "agent" as const }));
const edges = [
  { from: "brief", to: "a" },
  { from: "brief", to: "b" },
  { from: "a", to: "join" },
  { from: "b", to: "join" },
];

test("steps with the same longest path from a root share a level", () => {
  const levels = graphLayout(steps, edges);
  assert.deepEqual(levels, [["brief"], ["a", "b"], ["join"]]);
});

test("a step with no edges sits at the first level", () => {
  assert.deepEqual(graphLayout(steps.slice(0, 2), []), [["brief", "a"]]);
});

const ev = (seq: number, step: string, status: string, tokens: number | null = null) => ({
  seq,
  step,
  status,
  reason: null,
  tokens,
});

test("attempts count started events; tokens sum over the attempts", () => {
  const summary = summarizeSteps([
    ev(1, "a", "started"),
    ev(2, "a", "started"),
    ev(3, "a", "succeeded", 40),
  ]);
  assert.equal(summary["a"]?.status, "succeeded");
  assert.equal(summary["a"]?.retries, 1);
  assert.equal(summary["a"]?.tokens, 40);
});

test("steps whose runs interleave are overlapping; sequential ones are not", () => {
  const summary = summarizeSteps([
    ev(1, "a", "started"),
    ev(2, "b", "started"),
    ev(3, "a", "succeeded"),
    ev(4, "b", "succeeded"),
    ev(5, "c", "started"),
    ev(6, "c", "succeeded"),
  ]);
  assert.deepEqual(summary["a"]?.alongside, ["b"]);
  assert.deepEqual(summary["b"]?.alongside, ["a"]);
  assert.deepEqual(summary["c"]?.alongside, []);
});

test("a step still running overlaps one that starts before it ends", () => {
  const summary = summarizeSteps([ev(1, "a", "started"), ev(2, "b", "started")]);
  assert.deepEqual(summary["a"]?.alongside, ["b"]);
});
