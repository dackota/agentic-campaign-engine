import assert from "node:assert/strict";
import { test } from "node:test";
import { flagLabel, kindDescription, kindLabel, stepLabel, workflowLabel } from "./labels.ts";
import { StepKindValues } from "./workflow.gen.ts";

test("every step kind in the workflow schema has a label", () => {
  for (const kind of StepKindValues) {
    assert.ok(kindLabel(kind).length > 0, kind);
    assert.notEqual(kindLabel(kind), kind);
  }
});

test("known step and workflow ids read as plain names", () => {
  assert.equal(stepLabel("email_writer"), "Email");
  assert.equal(stepLabel("one_pager"), "One-pager");
  assert.equal(workflowLabel("threat-report-to-campaign"), "Threat report to campaign");
});

test("unknown ids are made readable", () => {
  assert.equal(stepLabel("constructor"), "Constructor");
  assert.equal(stepLabel("first_draft"), "First draft");
  assert.equal(workflowLabel("my-workflow"), "My workflow");
});

test("flag checks read as plain words", () => {
  for (const check of ["uncited_fact", "banned_claim", "off_brand_word", "length"]) {
    assert.ok(!flagLabel(check).includes("_"), check);
    assert.notEqual(flagLabel(check), check);
  }
});

test("every step kind has a one-line description", () => {
  for (const kind of StepKindValues) {
    const text = kindDescription(kind);
    assert.ok(text.length > 0 && !text.includes("\n"), kind);
  }
});
