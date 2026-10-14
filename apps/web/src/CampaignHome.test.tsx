import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { CampaignHome } from "./CampaignHome";
import { campaign, me } from "./testSupport";

const mine = campaign({
  id: "c1",
  report: "Volt Typhoon targets edge routers\nActors exploit VPNs.",
  created_by: "user-me",
  cost: { input_tokens: 1, output_tokens: 1, total_tokens: 2, cost_usd: 0.0162, steps: [] },
});

test("each campaign card shows title, status, owner, start time and cost", () => {
  render(<CampaignHome me={me("owner")} campaigns={[mine]} go={() => {}} />);

  const card = within(screen.getByRole("listitem"));
  expect(card.getByRole("link", { name: "Volt Typhoon targets edge routers" }).getAttribute("href")).toBe(
    "/campaigns/c1",
  );
  expect(card.getByTestId("card-status").textContent).toContain("Waiting for approval");
  expect(card.getByTestId("card-owner").textContent).toBe("You");
  expect(card.getByTestId("card-started").textContent).not.toBe("");
  expect(card.getByTestId("card-cost").textContent).toBe("$0.02");
});

test("a campaign someone else started says a teammate", () => {
  render(<CampaignHome me={me("owner")} campaigns={[{ ...mine, created_by: "user-other" }]} go={() => {}} />);
  expect(screen.getByTestId("card-owner").textContent).toBe("A teammate");
});

test("opening a card goes to the campaign's own URL without a page load", async () => {
  const go = vi.fn();
  render(<CampaignHome me={me("owner")} campaigns={[mine]} go={go} />);
  await userEvent.click(screen.getByRole("link", { name: /Volt Typhoon/ }));
  expect(go).toHaveBeenCalledWith("/campaigns/c1");
});

test("an owner with no campaigns sees a friendly empty state with a start button", async () => {
  const go = vi.fn();
  render(<CampaignHome me={me("owner")} campaigns={[]} go={go} />);

  expect(screen.getByText(/No campaigns yet/)).toBeTruthy();
  expect(screen.queryByRole("list", { name: "Campaigns" })).toBeNull();
  const start = screen.getByRole("link", { name: "Start your first campaign" });
  expect(start.getAttribute("href")).toBe("/campaigns/new");
  await userEvent.click(start);
  expect(go).toHaveBeenCalledWith("/campaigns/new");
});

test("an owner sees the New campaign button", () => {
  render(<CampaignHome me={me("owner")} campaigns={[mine]} go={() => {}} />);
  expect(screen.getByRole("link", { name: "New campaign" }).getAttribute("href")).toBe("/campaigns/new");
});

test("a viewer sees the campaigns but no way to start one", () => {
  const { unmount } = render(<CampaignHome me={me("viewer")} campaigns={[mine]} go={() => {}} />);
  expect(screen.getByRole("heading", { name: "Campaigns" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "New campaign" })).toBeNull();
  unmount();

  render(<CampaignHome me={me("viewer")} campaigns={[]} go={() => {}} />);
  expect(screen.queryByRole("link", { name: "Start your first campaign" })).toBeNull();
  expect(screen.getByText(/An owner on your team can start one/)).toBeTruthy();
});

test("home says it is loading before the first read, not that it is empty", () => {
  render(<CampaignHome me={me("owner")} campaigns={null} go={() => {}} />);
  expect(screen.getByRole("status").textContent).toBe("Loading your campaigns…");
  expect(screen.queryByText(/No campaigns yet/)).toBeNull();
});
