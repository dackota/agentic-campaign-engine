import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { Builder, moveStep, toWorkflow } from "./Builder";
import { stubApi } from "./testSupport";
import type { WorkflowStep } from "./workflow.gen";

interface Body {
  steps: WorkflowStep[];
}

/** A stand-in for the API's checks: just the two rules these tests need. The API tests prove the real ones. */
function validate({ steps }: Body) {
  const rejections = [];
  if (steps.length === 0) rejections.push({ rule: "invalid_shape", message: "steps: [] should be non-empty" });
  steps.forEach((s, i) => {
    if (s.kind !== "publish") return;
    const before = steps.slice(0, i).map((b) => b.kind);
    const message = !before.includes("approval")
      ? `publish step '${s.id}' needs an approval step before it, so nothing goes out unreviewed`
      : !before.includes("agent")
        ? `publish step '${s.id}' needs an agent step before it to write the content`
        : null;
    const rule = before.includes("approval") ? "publish_without_content" : "publish_without_approval";
    if (message) rejections.push({ rule, message });
  });
  return { rejections };
}

function renderBuilder() {
  let saved: number[] = [];
  const calls = stubApi({
    "POST /workflows/validate": (body) => validate(body as Body),
    "GET /workflows/my-flow/versions": () => saved.map((version) => ({ version })),
    "POST /workflows/my-flow/versions": () => {
      saved = [1];
      return { version: 1 };
    },
  });
  render(<Builder />);
  return calls;
}
const steps = () => within(screen.getByRole("list", { name: "Workflow steps" })).queryAllByRole("listitem");
const order = () => steps().map((s) => s.querySelector("strong")?.textContent);
const click = (name: string) => userEvent.click(screen.getByRole("button", { name }));
const useTemplate = () => click("Use template: Threat report to campaign");
const save = () => screen.getByRole("button", { name: "Save version" }) as HTMLButtonElement;

test("the builder opens on a template gallery with no error", () => {
  renderBuilder();
  expect(screen.getByRole("button", { name: "Use template: Threat report to campaign" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Start a blank workflow" })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a blank workflow shows a palette that explains each step, and asks for a first step", async () => {
  renderBuilder();
  await click("Start a blank workflow");

  const palette = within(screen.getByRole("list", { name: "Step palette" })).getAllByRole("listitem");
  expect(palette).toHaveLength(5);
  expect(palette.find((p) => p.textContent?.includes("Approval"))?.textContent).toContain("A person says yes");
  expect(await screen.findByText("Add at least one step")).toBeTruthy();
});

test("a message about a step shows next to that step, and Save version waits until it is fixed", async () => {
  renderBuilder();
  await click("Start a blank workflow");
  await click("Add Approval");

  expect(steps()[0]?.textContent).toContain("An approval step needs a step before it");
  expect(save().disabled).toBe(true);

  await click("Add Publish");
  await waitFor(() => expect(steps()[1]?.textContent).toContain("needs an AI step before it"));
});

// Whether the handle keeps the focus after a move needs a real browser (jsdom keeps it on any move): the e2e builder test checks it.
test("a step moves with the keyboard", async () => {
  renderBuilder();
  await useTemplate();
  expect(order()).toEqual(["Email draft", "Approval", "Publish"]);

  const handle = screen.getByRole("button", { name: "Move Approval" });
  handle.focus();
  await userEvent.keyboard("{ArrowDown}");
  expect(order()).toEqual(["Email draft", "Publish", "Approval"]);
  await waitFor(() => expect(steps()[1]?.textContent).toContain("needs an approval step before it"));

  await userEvent.keyboard("{ArrowUp}");
  expect(order()).toEqual(["Email draft", "Approval", "Publish"]);
});

test("a step cannot be moved past either end", async () => {
  renderBuilder();
  await useTemplate();
  const first = screen.getByRole("button", { name: "Move Email draft" });
  first.focus();
  await userEvent.keyboard("{ArrowUp}");
  expect(order()).toEqual(["Email draft", "Approval", "Publish"]);
});

test("a step moves by drag and drop", async () => {
  renderBuilder();
  await useTemplate();
  fireEvent.dragStart(steps()[2]!);
  fireEvent.drop(steps()[1]!);
  expect(order()).toEqual(["Email draft", "Publish", "Approval"]);
});

test("saving sends the steps as a chain with the retry setting, and lists the new version", async () => {
  const calls = renderBuilder();
  await useTemplate();
  await userEvent.type(within(steps()[0]!).getByLabelText("Retry attempts"), "4");
  await userEvent.click(screen.getByLabelText("Workflow name"));
  await userEvent.paste("my-flow");
  await waitFor(() => expect(save().disabled).toBe(false));
  await userEvent.click(save());

  expect(await screen.findByText("Version 1")).toBeTruthy();
  const sent = calls.find((c) => c.method === "POST" && c.path === "/workflows/my-flow/versions")?.body;
  expect(sent).toEqual({
    steps: [{ id: "email_draft", kind: "agent", max_attempts: 4 }, { id: "approval", kind: "approval" }, { id: "publish", kind: "publish" }],
    edges: [{ from: "email_draft", to: "approval" }, { from: "approval", to: "publish" }],
  });
});

test("a workflow name the API would refuse keeps Save version disabled", async () => {
  renderBuilder();
  await useTemplate();
  await userEvent.click(screen.getByLabelText("Workflow name"));
  await userEvent.paste("My Flow");
  await waitFor(() => expect(screen.queryByText("Checking your workflow…")).toBeNull());
  expect(save().disabled).toBe(true);
});

const chain: WorkflowStep[] = ["a", "b", "c"].map((id) => ({ id, kind: "agent" as const }));

test("moveStep moves one step and leaves the original list alone", () => {
  expect(moveStep(chain, 2, 0).map((s) => s.id)).toEqual(["c", "a", "b"]);
  expect(chain.map((s) => s.id)).toEqual(["a", "b", "c"]);
  expect(moveStep(chain, 7, 0)).toBe(chain);
});

test("a workflow is a chain: each step starts after the one above it", () => {
  expect(toWorkflow(chain).edges).toEqual([{ from: "a", to: "b" }, { from: "b", to: "c" }]);
  expect(toWorkflow([]).edges).toEqual([]);
});
