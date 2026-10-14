import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, test } from "vitest";
import { RunGraph } from "./RunGraphView";
import type { WorkflowStep } from "./workflow.gen";

const agent = (id: string): WorkflowStep => ({ id, kind: "agent" });
const PARALLEL = ["brief", "writer_a", "writer_b", "preview"].map(agent);
const EDGES = [
  { from: "brief", to: "writer_a" },
  { from: "brief", to: "writer_b" },
  { from: "writer_a", to: "preview" },
  { from: "writer_b", to: "preview" },
];
const ev = (seq: number, step: string, status: string, tokens: number | null = null) => ({ seq, step, status, tokens });
// The brief took a failed first call, so it started twice; the two writers ran side by side.
const FINISHED = [
  ev(1, "brief", "started"),
  ev(2, "brief", "started"),
  ev(3, "brief", "succeeded", 40),
  ev(4, "writer_a", "started"),
  ev(5, "writer_b", "started"),
  ev(6, "writer_a", "succeeded", 10),
  ev(7, "writer_b", "succeeded", 10),
  ev(8, "preview", "started"),
  ev(9, "preview", "succeeded"),
];
const step = (id: string) => screen.getByTestId(`step-${id}`);

/** The graph with its own Details switch, as the run page has. */
function Graph({ dag, events }: { dag: WorkflowStep[]; events: ReturnType<typeof ev>[] }) {
  const [showDetails, setShowDetails] = useState(false);
  return (
    <>
      <button onClick={() => setShowDetails(true)}>Details</button>
      <RunGraph dag={dag} edges={EDGES} events={events} showDetails={showDetails} />
    </>
  );
}

test("one line is drawn for each edge of the workflow", () => {
  const { container } = render(<Graph dag={PARALLEL} events={[]} />);
  expect(container.querySelectorAll("[data-edge]")).toHaveLength(4);
  expect(container.querySelector('[data-edge="brief->writer_a"]')).toBeTruthy();
});

test("each step shows its final status once the run is over", () => {
  render(<Graph dag={PARALLEL} events={FINISHED} />);
  for (const id of ["brief", "writer_a", "writer_b", "preview"]) expect(step(id).textContent).toContain("Done");
});

test("a step that has not started is Waiting", () => {
  render(<Graph dag={PARALLEL} events={[ev(1, "brief", "started")]} />);
  expect(step("brief").textContent).toContain("Running");
  expect(step("preview").textContent).toContain("Waiting");
});

test("a step that ran twice shows 1 retry; the others do not", () => {
  render(<Graph dag={PARALLEL} events={FINISHED} />);
  expect(step("brief").textContent).toContain("1 retry");
  expect(step("writer_a").textContent).not.toContain("retry");
});

test("tokens and which steps ran alongside are behind Details", async () => {
  render(<Graph dag={PARALLEL} events={FINISHED} />);
  expect(step("brief").textContent).not.toContain("tokens");
  expect(step("writer_a").textContent).not.toContain("alongside");

  await userEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(step("brief").textContent).toMatch(/40 tokens/);
  expect(step("writer_a").textContent).toContain("alongside writer_b");
  expect(step("writer_b").textContent).toContain("alongside writer_a");
  expect(step("brief").textContent).not.toContain("alongside");
});

test("steps are listed in run order, with each one's status", () => {
  const dag = [agent("writer"), { id: "preview", kind: "render" as const }, { id: "approve", kind: "approval" as const }, { id: "publish", kind: "publish" as const }];
  render(<Graph dag={dag} events={[ev(1, "writer", "started"), ev(2, "writer", "succeeded")]} />);

  const items = screen.getByRole("list", { name: "Run steps" }).querySelectorAll("li");
  expect([...items].map((li) => li.textContent)).toEqual([
    expect.stringMatching(/^Writer/),
    expect.stringMatching(/^Preview/),
    expect.stringMatching(/^Approve/),
    expect.stringMatching(/^Publish/),
  ]);
  expect(step("writer").textContent).toContain("Done");
  expect(step("publish").textContent).toContain("Waiting");
});

test("the standard pipeline lists its steps in plain words before they run", () => {
  const dag = ["email_draft", "judge", "approval", "publish"].map(agent);
  render(<Graph dag={dag} events={[]} />);
  const items = screen.getByRole("list", { name: "Run steps" }).querySelectorAll("li");
  expect([...items].map((li) => li.querySelector("strong")?.textContent)).toEqual([
    "Email draft",
    "Quality check",
    "Approval",
    "Publish",
  ]);
});
