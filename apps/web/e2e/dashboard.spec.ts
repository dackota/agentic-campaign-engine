import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { accessTokenOf, chooseWorkflow, OWNER, signIn } from "./fixtures/sign-in";

const VIEWER = "dg-viewer@demo.example";
const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";
const RUN_WAIT_MS = 30_000;

/** Create a one-step workflow run and wait until the owner's page shows it finished. */
async function finishedCampaign(page: Page, title: string): Promise<void> {
  const name = `e2e-dash-${randomUUID().slice(0, 8)}`;
  const saved = await page.request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: {
      steps: [
        { id: "landing_page", kind: "agent" },
        { id: "judge", kind: "agent" },
      ],
      edges: [{ from: "landing_page", to: "judge" }],
    },
  });
  expect(saved.status()).toBe(201);
  await chooseWorkflow(page, name);
  await page.getByLabel("Threat report").fill(`${title}\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Finished", { timeout: RUN_WAIT_MS });
  await expect(page.getByTestId("judge-score-landing_page")).toBeVisible();
}

test("the dashboard shows a finished campaign's numbers and a trend across campaigns", async ({
  page,
}) => {
  const stamp = Date.now();
  await signIn(page, OWNER);
  await finishedCampaign(page, `Dash one ${stamp}`);
  await finishedCampaign(page, `Dash two ${stamp}`);

  await page.getByRole("button", { name: "Dashboard" }).click();

  const row = page.getByTestId(`dashboard-row-Dash one ${stamp}`);
  await expect(row.getByTestId("dashboard-status")).toHaveText("Finished");
  await expect(row.getByTestId("dashboard-cost")).toHaveText(/^\$\d+\.\d{2}$/);
  await expect(row.getByTestId("dashboard-quality")).toHaveText(/^[1-5](\.\d)?\/5$/);
  await expect(row.getByTestId("dashboard-click-rate")).toBeVisible();
  await expect(page.getByTestId("dashboard-runs")).not.toHaveText("0");
  await expect(page.getByTestId("dashboard-trend").getByRole("listitem")).not.toHaveCount(0);
  const trend = await page.getByTestId("dashboard-trend").getByRole("listitem").allTextContents();
  const one = trend.findIndex((t) => t.includes(`Dash one ${stamp}`));
  const two = trend.findIndex((t) => t.includes(`Dash two ${stamp}`));
  expect(one).toBeGreaterThanOrEqual(0);
  expect(two).toBeGreaterThan(one);
});

test("a viewer sees the dashboard with no edit controls", async ({ page }) => {
  await signIn(page, VIEWER);

  await page.getByRole("button", { name: "Dashboard" }).click();

  await expect(page.getByRole("heading", { name: "Team dashboard" })).toBeVisible();
  await expect(page.getByTestId("dashboard").getByRole("button")).toHaveCount(0);
  await expect(page.getByTestId("dashboard").locator("input, textarea, select")).toHaveCount(0);
});
