import { expect, test, type Browser, type Page } from "@playwright/test";
import { APPROVER, OWNER, signIn } from "./fixtures/sign-in";

// The fake Marketo's port is pinned in playwright.config.ts so a spec can steer its audience.
const marketoPort = process.env.ACE_MARKETO_PORT ?? "18090";
const AUDIENCE_URL = `http://127.0.0.1:${marketoPort}/_audience`;
const VIEWER = "dg-viewer@demo.example";
// Seed 1 opens variant A far more than B; at this speed days of engagement take seconds.
const SEED = 1;
const DAY_SPEED = 100_000;
const DEFAULT_SPEED = 86_400;
const SETTLE_MS = 30_000;

async function setAudience(page: Page, timeSpeed: number): Promise<void> {
  const response = await page.request.put(AUDIENCE_URL, {
    data: { seed: SEED, time_speed: timeSpeed },
  });
  expect(response.status()).toBe(204);
}

/** Send a campaign and wait until the A/B test calls its winner, which makes a learning. */
async function sendUntilWinner(page: Page, browser: Browser, report: string): Promise<Page> {
  await setAudience(page, DAY_SPEED);
  await signIn(page, OWNER);
  await page.getByLabel("Threat report").fill(report);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();

  const approverPage = await (await browser.newContext()).newPage();
  await signIn(approverPage, APPROVER);
  await approverPage.getByRole("button", { name: report }).click();
  await approverPage.getByRole("button", { name: "Approve" }).click();
  await expect(approverPage.getByTestId("ab-result")).toHaveText(/^Winner: [AB]/, {
    timeout: SETTLE_MS,
  });
  return approverPage;
}

test.afterEach(async ({ page }) => {
  await setAudience(page, DEFAULT_SPEED);
});

test("an approver sees each learning's source campaign and deletes a learning; a viewer cannot", async ({
  page,
  browser,
}) => {
  const report = `Volt Typhoon learns ${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const approverPage = await sendUntilWinner(page, browser, report);

  const viewerPage = await (await browser.newContext()).newPage();
  await signIn(viewerPage, VIEWER);
  await viewerPage.getByRole("button", { name: "Learnings" }).click();
  const seen = viewerPage.getByRole("listitem").filter({ hasText: report });
  await expect(seen).toHaveCount(1);
  await expect(seen.getByRole("button", { name: "Delete" })).toHaveCount(0);

  await approverPage.getByRole("button", { name: "Learnings" }).click();
  const learning = approverPage.getByRole("listitem").filter({ hasText: report });
  await expect(learning).toHaveCount(1);
  await expect(learning.getByTestId("learning-text")).not.toBeEmpty();
  await expect(learning.getByTestId("learning-reason")).toHaveText(/^Variant [AB] won/);
  await learning.getByRole("button", { name: report }).click();
  await expect(approverPage.getByTestId("draft-subject")).not.toBeEmpty();

  await approverPage.getByRole("button", { name: "Learnings" }).click();
  await approverPage
    .getByRole("listitem")
    .filter({ hasText: report })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect(approverPage.getByRole("listitem").filter({ hasText: report })).toHaveCount(0);
});
