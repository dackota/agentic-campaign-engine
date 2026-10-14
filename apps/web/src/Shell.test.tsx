import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Header, ViewNav } from "./Shell";
import { me } from "./testSupport";

test("the header shows the product, the team and the user, and the user menu signs out", async () => {
  const onSignOut = vi.fn();
  render(<Header me={{ ...me("approver"), email: "dg-approver@demo.example" }} onSignOut={onSignOut} />);

  const header = screen.getByRole("banner");
  expect(header.textContent).toContain("Agentic Campaign Engine");
  expect(within(header).getByTestId("team").textContent).toBe("demand-gen");
  expect(within(header).getByTestId("signed-in-as").textContent).toBe("dg-approver@demo.example");
  await userEvent.click(within(header).getByRole("button", { name: "Sign out" }));
  expect(onSignOut).toHaveBeenCalledOnce();
});

test("a user with no team sees No team", () => {
  render(<Header me={{ ...me("owner"), team: null }} onSignOut={() => {}} />);
  expect(screen.getByTestId("team").textContent).toBe("No team");
});

test("the navigation marks only the current page", () => {
  render(<ViewNav me={me("owner")} view="dashboard" onView={() => {}} />);

  const current = screen.getByRole("navigation").querySelectorAll('[aria-current="page"]');
  expect(current).toHaveLength(1);
  expect(current[0]).toBe(screen.getByRole("button", { name: "Dashboard" }));
});

test("choosing a page tells the app which one", async () => {
  const onView = vi.fn();
  render(<ViewNav me={me("owner")} view="campaigns" onView={onView} />);
  await userEvent.click(screen.getByRole("button", { name: "Workflow builder" }));
  expect(onView).toHaveBeenCalledWith("builder");
});

test("only an approver has the Inbox", () => {
  const { unmount } = render(<ViewNav me={me("owner")} view="campaigns" onView={() => {}} />);
  expect(screen.queryByRole("button", { name: "Inbox" })).toBeNull();
  unmount();
  render(<ViewNav me={me("approver")} view="campaigns" onView={() => {}} />);
  expect(screen.getByRole("button", { name: "Inbox" })).toBeTruthy();
});
