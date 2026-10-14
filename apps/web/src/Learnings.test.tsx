import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Learnings } from "./Learnings";
import type { Learning } from "./learningsApi";
import { stubApi } from "./testSupport";

const LEARNING: Learning = {
  id: "l1",
  text: "Lead with the patch deadline",
  reason: "Variant A won with 91% confidence",
  campaign_id: "c1",
  campaign_title: "Volt Typhoon learns",
  created_at: "2026-10-11T10:00:00Z",
};

function renderLearnings(canDelete: boolean, onOpenCampaign: (id: string) => void = () => {}) {
  let stored = [LEARNING];
  const calls = stubApi({
    "GET /learnings": () => stored,
    "DELETE /learnings/l1": () => {
      stored = [];
      return {};
    },
  });
  render(<Learnings canDelete={canDelete} onOpenCampaign={onOpenCampaign} onSignOut={() => {}} />);
  return calls;
}

test("each learning shows its text, why it was kept in plain words, and its source campaign", async () => {
  renderLearnings(false);
  expect((await screen.findByTestId("learning-text")).textContent).toBe("Lead with the patch deadline");
  expect(screen.getByTestId("learning-reason").textContent).toBe("Version A won with 91% confidence");
  expect(screen.getByRole("button", { name: "Volt Typhoon learns" })).toBeTruthy();
});

test("a learning of three stored lines shows the first as its title and the others as separate lines", async () => {
  const multiLine = {
    ...LEARNING,
    text: "Act now: Volt Typhoon\nWhat the new threat means for you\nRead the full advisory",
  };
  stubApi({ "GET /learnings": [multiLine] });
  render(<Learnings canDelete={false} onOpenCampaign={() => {}} onSignOut={() => {}} />);

  expect((await screen.findByTestId("learning-text")).textContent).toBe("Act now: Volt Typhoon");
  expect(screen.getAllByTestId("learning-detail").map((el) => el.textContent)).toEqual([
    "What the new threat means for you",
    "Read the full advisory",
  ]);
});

test("stray spaces and blank lines in a stored learning never make an empty title or empty lines", async () => {
  stubApi({
    "GET /learnings": [
      { ...LEARNING, id: "l2", text: "  Lead with the patch deadline  \n\n   \n  Read the advisory " },
      { ...LEARNING, id: "l3", text: "  \n " },
    ],
  });
  render(<Learnings canDelete={false} onOpenCampaign={() => {}} onSignOut={() => {}} />);

  await screen.findAllByTestId("learning-reason");
  expect(screen.getAllByTestId("learning-text").map((el) => el.textContent)).toEqual(["Lead with the patch deadline"]);
  expect(screen.getAllByTestId("learning-detail").map((el) => el.textContent)).toEqual(["Read the advisory"]);
});

test("the source campaign opens from its name", async () => {
  const onOpen = vi.fn();
  renderLearnings(false, onOpen);
  await userEvent.click(await screen.findByRole("button", { name: "Volt Typhoon learns" }));
  expect(onOpen).toHaveBeenCalledWith("c1");
});

test("someone who cannot delete sees no Delete button", async () => {
  renderLearnings(false);
  await screen.findByTestId("learning-text");
  expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
});

test("an approver deletes a learning and it leaves the list", async () => {
  const calls = renderLearnings(true);
  await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() => expect(screen.queryByTestId("learning-text")).toBeNull());
  expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/learnings/l1"]);
});

test("with no learnings the page says when they appear", async () => {
  stubApi({ "GET /learnings": [] });
  render(<Learnings canDelete onOpenCampaign={() => {}} onSignOut={() => {}} />);
  expect((await screen.findByText(/No learnings yet/)).textContent).toContain("A/B test picks a winner");
});
