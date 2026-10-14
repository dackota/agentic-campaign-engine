import assert from "node:assert/strict";
import { test } from "vitest";
import type { Campaign } from "./api.ts";
import {
  abResultText,
  campaignTitle,
  costText,
  dollarsOf,
  dollarsText,
  failureText,
  flagLabel,
  kindDescription,
  kindLabel,
  nextStepText,
  stepLabel,
  stepStatusLabel,
  workflowLabel,
} from "./labels.ts";
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

const STATUSES = ["drafting", "awaiting_approval", "sending", "sent", "failed", "retrying", "finished", "budget_paused"] as const;

test("every campaign status has a next-step sentence", () => {
  for (const status of STATUSES) {
    const text = nextStepText(status);
    assert.ok(text.length > 0 && text.endsWith(".") && !text.includes("\n"), status);
    assert.ok(!text.includes("_"), status);
  }
  assert.equal(nextStepText("awaiting_approval"), "Waiting for an approver.");
});

test("step statuses read as plain words", () => {
  assert.equal(stepStatusLabel("started"), "Running");
  assert.equal(stepStatusLabel("succeeded"), "Done");
  assert.equal(stepStatusLabel("failed"), "Failed");
  assert.equal(stepStatusLabel("pending"), "Waiting");
});

test("a failure reason reads in plain words, without step ids or raw errors", () => {
  const raw = "step 'writer' failed after 2 attempts: agent returned an error: {'code': -32000}";
  assert.equal(failureText(raw), "The Writer step did not finish after 2 attempts.");
  assert.equal(failureText("step 'email_writer' failed after 1 attempts: x"), "The Email step did not finish after 1 attempt.");
  assert.equal(failureText("step 'writer' failed: contract broken"), "The Writer step did not finish.");
  assert.equal(failureText(null), "A step did not finish.");
  assert.equal(failureText("something odd {}"), "A step did not finish.");
});

test("cost reads as tokens and four-decimal dollars; main screens read dollars and cents", () => {
  const usage = { input_tokens: 2000, output_tokens: 1000, total_tokens: 3000, cost_usd: 0.0162 };
  assert.equal(costText(usage), "3,000 tokens, $0.0162");
  assert.equal(costText({ ...usage, total_tokens: 4500, cost_usd: 0.0243 }), "4,500 tokens, $0.0243");
  assert.equal(dollarsText(0.0162), "$0.02");
  assert.equal(dollarsText(0.042), "$0.04");
});

test("a blank budget box means no limit; a typed one is a number", () => {
  assert.equal(dollarsOf("  "), null);
  assert.equal(dollarsOf("0.01"), 0.01);
});

test("the A/B call names the winner and rounds confidence down", () => {
  assert.equal(abResultText({ status: "no_decision", winner: null, confidence: null }), "No decision yet");
  assert.equal(abResultText({ status: "winner", winner: "A", confidence: 0.857 }), "Version A won, 85% confident");
  assert.equal(abResultText({ status: "winner", winner: "B", confidence: null }), "No decision yet");
});

test("a campaign is titled by the first line of its report", () => {
  assert.equal(campaignTitle({ id: "c1", report: "Volt Typhoon\nActors exploit VPNs" } as Campaign), "Volt Typhoon");
});
