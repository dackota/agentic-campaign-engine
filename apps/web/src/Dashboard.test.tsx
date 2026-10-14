import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { Dashboard } from "./Dashboard";
import type { DashboardRow, DashboardTotals } from "./dashboardApi";
import { stubApi } from "./testSupport";

const row = (title: string, over: Partial<DashboardRow> = {}): DashboardRow => ({
  id: `id-${title}`,
  title,
  status: "finished",
  created_at: "2026-10-11T10:00:00Z",
  cost_usd: 0.0243,
  quality_score: 4.5,
  click_rate: 0.32,
  ...over,
});
const TOTALS: DashboardTotals = { runs: 2, cost_usd: 0.0486, quality_score: 4.2, click_rate: 0.3 };
const ROWS = [row("Dash one"), row("Dash two", { quality_score: null, click_rate: null, status: "failed" })];

async function renderDashboard(campaigns: DashboardRow[] = ROWS, totals = TOTALS) {
  stubApi({ "GET /dashboard": { campaigns, totals } });
  render(<Dashboard onSignOut={() => {}} />);
  await screen.findByRole("heading", { name: "Team dashboard" });
}
const cell = (title: string, id: string) => within(screen.getByTestId(`dashboard-row-${title}`)).getByTestId(id).textContent;

test("each campaign row shows its status, cost, quality and click rate", async () => {
  await renderDashboard();
  expect(cell("Dash one", "dashboard-status")).toBe("Finished");
  expect(cell("Dash one", "dashboard-cost")).toBe("$0.02");
  expect(cell("Dash one", "dashboard-quality")).toBe("4.5/5");
  expect(cell("Dash one", "dashboard-click-rate")).toBe("32%");
});

test("a campaign with no score or clicks yet shows n/a, not a number", async () => {
  await renderDashboard();
  expect(cell("Dash two", "dashboard-status")).toBe("Failed");
  expect(cell("Dash two", "dashboard-quality")).toBe("n/a");
  expect(cell("Dash two", "dashboard-click-rate")).toBe("n/a");
});

test("four headline tiles show the team's totals", async () => {
  await renderDashboard();
  const tiles = within(screen.getByTestId("dashboard-tiles")).getAllByRole("listitem");
  expect(tiles.map((t) => t.querySelector(".tile-label")?.textContent)).toEqual([
    "Campaigns run",
    "Average quality",
    "Average click rate",
    "Total cost",
  ]);
  expect(screen.getByTestId("dashboard-runs").textContent).toBe("2");
  expect(screen.getByTestId("dashboard-total-quality").textContent).toBe("4.2/5");
  expect(screen.getByTestId("dashboard-total-click-rate").textContent).toBe("30%");
  expect(screen.getByTestId("dashboard-total-cost").textContent).toBe("$0.05");
});

test("the trend lists the campaigns oldest first, in words", async () => {
  await renderDashboard();
  const items = within(screen.getByTestId("dashboard-trend")).getAllByRole("listitem");
  expect(items.map((i) => i.textContent)).toEqual([
    "Dash one: quality 4.5/5, click rate 32%",
    "Dash two: quality n/a, click rate n/a",
  ]);
});

test("the trend chart is an SVG with labeled axes and a text alternative", async () => {
  await renderDashboard();
  const chart = screen.getByTestId("dashboard-trend-chart");
  expect(chart.tagName.toLowerCase()).toBe("svg");
  expect(chart.getAttribute("role")).toBe("img");
  expect(chart.getAttribute("aria-label")).toMatch(/click rate.*quality/i);
  const labels = [...chart.querySelectorAll("text")].map((t) => t.textContent);
  expect(labels.filter((l) => l === "Campaign")).toHaveLength(1);
  expect(labels).toContain("Click rate");
  expect(labels).toContain("Quality");
});

test("a team with no campaigns sees what to do next, not an empty chart and table", async () => {
  await renderDashboard([], { runs: 0, cost_usd: 0, quality_score: null, click_rate: null });
  expect(screen.getByText("No campaigns yet. Start one from New campaign, then come back to see how it did.")).toBeTruthy();
  expect(screen.queryByTestId("dashboard-trend-chart")).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByTestId("dashboard-total-quality").textContent).toBe("n/a");
});

test("the dashboard is read-only: it has no buttons or fields", async () => {
  await renderDashboard();
  const dashboard = screen.getByTestId("dashboard");
  expect(dashboard.querySelectorAll("button, input, textarea, select")).toHaveLength(0);
});

test("the dashboard says it is loading, then shows the error if it cannot load", async () => {
  stubApi({ "GET /dashboard": new Response("db down", { status: 500 }) });
  render(<Dashboard onSignOut={() => {}} />);
  expect(screen.getByRole("status").textContent).toBe("Loading the dashboard…");
  expect((await screen.findByRole("alert")).textContent).toContain("500");
});
