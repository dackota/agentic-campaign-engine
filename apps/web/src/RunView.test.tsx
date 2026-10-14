import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import type { Campaign } from "./api";
import { RunView } from "./RunView";
import { campaign, me, stubApi } from "./testSupport";

const EMAIL = { subject: "Patch your VPN", preheader: "Volt Typhoon is active", body: "Hello team", call_to_action: "Patch" };
const ev = (seq: number, step: string, status: string, tokens: number | null = null) => ({
  seq,
  step,
  status,
  reason: null,
  tokens,
});

/** The run page for `c`, seen by `props.me` (an approver who did not create it, unless told otherwise). */
function renderRun(c: Campaign, props: Partial<ComponentProps<typeof RunView>> = {}) {
  stubApi({ "GET /campaigns/c1/preview": () => new Response("<h1>Volt Typhoon</h1>") });
  const all = { me: me("approver"), campaign: c, events: [], onApprove: () => {}, onRetry: () => {}, onRaiseBudget: () => {}, ...props };
  return render(<RunView {...all} />);
}
const text = (id: string) => screen.getByTestId(id).textContent;

test("a drafting run says Drafting, what happens next, and which step is running", () => {
  renderRun(campaign({ status: "drafting", steps: [{ id: "email_draft", kind: "agent" }] }), {
    events: [ev(1, "email_draft", "started")],
  });
  expect(text("run-status")).toBe("Drafting");
  expect(text("next-step")).toBe("The AI is writing the draft.");
  expect(text("step-email_draft")).toContain("Running");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Volt Typhoon targets edge routers");
});

test("the same run, updated with no reload, goes to Waiting for approval with its step Done", () => {
  const steps = [{ id: "email_draft", kind: "agent" as const }];
  const { rerender } = renderRun(campaign({ status: "drafting", steps }), { events: [ev(1, "email_draft", "started")] });
  const props = { me: me("approver"), onApprove: () => {}, onRetry: () => {}, onRaiseBudget: () => {} };

  rerender(<RunView {...props} campaign={campaign({ status: "awaiting_approval", steps })} events={[ev(1, "email_draft", "started"), ev(2, "email_draft", "succeeded")]} />);

  expect(text("run-status")).toBe("Waiting for approval");
  expect(text("next-step")).toBe("Waiting for an approver.");
  expect(text("step-email_draft")).toContain("Done");
});

test("quality, cost and draft show as cards, with the email in a closed sandbox", async () => {
  renderRun(campaign({ draft: EMAIL }));
  for (const name of ["Quality", "Cost", "Draft"]) expect(screen.getByRole("region", { name })).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Cost" })).getByTestId("run-cost")).toBeTruthy();
  expect(text("draft-subject")).toBe("Patch your VPN");

  const frame = screen.getByTitle("Email preview") as HTMLIFrameElement;
  expect(frame.getAttribute("sandbox")).toBe("");
  await waitFor(() => expect(frame.srcdoc).toContain("Volt Typhoon"));
});

test("before the AI finishes there is a note where the draft will appear", () => {
  renderRun(campaign({ draft: null }));
  expect(screen.getByText("The draft appears here when the AI finishes writing it.")).toBeTruthy();
  expect(screen.queryByTestId("draft-subject")).toBeNull();
});

test("the raw draft text is behind Details", async () => {
  renderRun(campaign({ draft: EMAIL }));
  expect(screen.queryByTestId("draft-body")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(text("draft-body")).toBe("Hello team");
});

test("a sent run shows its receipt; one not sent yet shows none", () => {
  const { unmount } = renderRun(campaign({ status: "awaiting_approval" }));
  expect(screen.queryByTestId("receipt")).toBeNull();
  unmount();
  renderRun(campaign({ status: "sent", receipt: "mk-12345" }));
  expect(text("receipt")).toBe("mk-12345");
});

test("the A/B result shows after the send: no decision yet, or the winner and its confidence", () => {
  const before = renderRun(campaign({ status: "awaiting_approval" }));
  expect(screen.queryByTestId("ab-result")).toBeNull();
  before.unmount();
  const open = renderRun(campaign({ status: "sent" }));
  expect(text("ab-result")).toBe("No decision yet");
  open.unmount();
  renderRun(campaign({ status: "sent", ab_result: { status: "winner", winner: "A", confidence: 0.857 } }));
  expect(text("ab-result")).toBe("Version A won, 85% confident");
});

test("the judge's score and reason show for each asset", () => {
  renderRun(campaign({ scores: [{ step: "landing_page", score: 4, reason: "Clear and on brand" }] }));
  expect(text("judge-score-landing_page")).toBe("4/5");
  expect(text("judge-reason-landing_page")).toBe("Clear and on brand");
});

test("with no scores yet the quality card says so", () => {
  renderRun(campaign({ scores: [] }));
  expect(screen.getByText("No quality check yet.")).toBeTruthy();
});

test("the workflow shows by name; its raw id and the run id sit behind Details", async () => {
  renderRun(campaign({ workflow: "threat-report-to-campaign", workflow_version: 1 }));
  expect(text("workflow-version")).toBe("Threat report to campaign version 1");
  expect(screen.queryByTestId("workflow-id")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(text("workflow-id")).toBe("threat-report-to-campaign");
});

const FAILED = campaign({
  status: "failed",
  failure_reason: "step 'writer' failed after 2 attempts: agent returned an error: {'code': -32000}",
  steps: [{ id: "writer", kind: "agent" }],
});

test("a failed step shows its reason in plain words; the raw error is behind Details", async () => {
  renderRun(FAILED, { events: [ev(1, "writer", "failed")] });
  expect(text("step-writer")).toContain("Failed");
  expect(text("next-step")).toContain("retry");
  const reason = screen.getByRole("alert");
  expect(reason.textContent).toBe("The Writer step did not finish after 2 attempts.");
  expect(reason.textContent).not.toContain("-32000");
  expect(screen.queryByTestId("failure-raw")).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(text("failure-raw")).toContain("agent returned an error");
});

test("bad agent output reads as a plain failure, with no draft", () => {
  renderRun(campaign({ status: "failed", failure_reason: "step 'email_draft' failed: contract broken" }));
  expect(screen.getByRole("alert").textContent).toBe("The Email draft step did not finish.");
  expect(screen.queryByTestId("draft-subject")).toBeNull();
});

test("the main view has no raw ids or token counts; Details brings them back", async () => {
  const steps = [
    { id: "email_writer", kind: "agent" as const },
    { id: "one_pager", kind: "agent" as const },
  ];
  const cost = { input_tokens: 0, output_tokens: 0, total_tokens: 700, cost_usd: 0.0162, steps: [] };
  renderRun(campaign({ steps, cost }), { events: [ev(1, "email_writer", "succeeded", 700), ev(2, "one_pager", "succeeded", 0)] });
  const main = document.body;

  expect(main.textContent).toContain("One-pager");
  expect(main.textContent).toMatch(/\$\d+\.\d\d(?!\d)/);
  for (const raw of ["email_writer", "one_pager", "tokens"]) expect(main.textContent).not.toContain(raw);

  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(main.textContent).toContain("tokens");
  expect(main.textContent).toContain("email_writer");
});

test("cost shows in dollars and cents, with tokens and the exact cost per step behind Details", async () => {
  const usage = { input_tokens: 0, output_tokens: 0 };
  const cost = {
    ...usage,
    total_tokens: 4500,
    cost_usd: 0.0243,
    steps: [
      { ...usage, step: "email_draft", model: "m", total_tokens: 3000, cost_usd: 0.0162 },
      { ...usage, step: "judge", model: "m", total_tokens: 1500, cost_usd: 0.0081 },
    ],
  };
  renderRun(campaign({ cost }));
  expect(text("run-cost")).toBe("$0.02");
  expect(screen.queryByTestId("run-tokens")).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(text("step-cost-email_draft")).toBe("3,000 tokens, $0.0162");
  expect(text("step-cost-judge")).toBe("1,500 tokens, $0.0081");
  expect(text("run-tokens")).toBe("4,500 tokens, $0.0243");
});

test("the Retry step button is for an owner, on a failed run only", async () => {
  const retried: string[] = [];
  const { unmount } = renderRun(FAILED, { me: me("owner"), onRetry: (id) => retried.push(id) });
  await userEvent.click(screen.getByRole("button", { name: "Retry step" }));
  expect(retried).toEqual(["c1"]);
  unmount();

  for (const roles of [["viewer"], ["approver"]]) {
    const view = renderRun(FAILED, { me: me(...roles) });
    expect(screen.queryByRole("button", { name: "Retry step" })).toBeNull();
    view.unmount();
  }
  renderRun(campaign({ status: "finished" }), { me: me("owner") });
  expect(screen.queryByRole("button", { name: "Retry step" })).toBeNull();
});

test("Approve is for an approver who did not create the campaign, while it waits", async () => {
  const approved: string[] = [];
  const first = renderRun(campaign(), { onApprove: (id) => approved.push(id) });
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(approved).toEqual(["c1"]);
  first.unmount();

  const own = renderRun(campaign({ created_by: "user-me" }), { me: me("approver") });
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  own.unmount();
  const ownerOnly = renderRun(campaign(), { me: me("owner") });
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  ownerOnly.unmount();
  renderRun(campaign({ status: "sent" }));
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
});

test("a run paused at its budget lets an owner raise it, and nobody else", async () => {
  const raised: [string, number][] = [];
  const paused = campaign({ status: "budget_paused", budget_usd: 0.01, steps: [{ id: "second", kind: "agent" }] });
  const first = renderRun(paused, { me: me("owner"), onRaiseBudget: (id, usd) => raised.push([id, usd]) });
  expect(text("run-status")).toBe("Paused at budget");
  expect(text("run-budget")).toBe("$0.01");
  expect(text("step-second")).toContain("Waiting");

  const raise = screen.getByRole("button", { name: "Raise budget" }) as HTMLButtonElement;
  expect(raise.disabled).toBe(true);
  await userEvent.type(screen.getByLabelText("New budget (USD)"), "1");
  await userEvent.click(raise);
  expect(raised).toEqual([["c1", 1]]);
  first.unmount();

  renderRun(paused, { me: me("viewer") });
  expect(screen.queryByLabelText("New budget (USD)")).toBeNull();
});
