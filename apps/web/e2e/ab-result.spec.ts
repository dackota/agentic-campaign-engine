import { expect, test, type Browser, type Page } from "@playwright/test";
import { APPROVER, OWNER, signIn, chooseQuickDraft } from "./fixtures/sign-in";

// playwright.config.ts sets the fake Marketo's port before the workers start, so a spec can steer its audience.
const marketoPort = process.env.ACE_MARKETO_PORT;
if (!marketoPort) throw new Error("ACE_MARKETO_PORT is unset: run the specs through playwright.config.ts");
const AUDIENCE_URL = `http://127.0.0.1:${marketoPort}/_audience`;
// Seed 1 opens variant A far more than B. The default speed is a simulated day per second.
const SEED = 1;
const SLOW_SPEED = 1; // an hour of simulated engagement takes an hour: nothing arrives in the test
const DAY_SPEED = 100_000; // days of engagement arrive within seconds
const DEFAULT_SPEED = 86_400;
const SETTLE_MS = 30_000;

async function setAudience(page: Page, timeSpeed: number): Promise<void> {
  const response = await page.request.put(AUDIENCE_URL, {
    data: { seed: SEED, time_speed: timeSpeed },
  });
  expect(response.status()).toBe(204);
}

async function sendCampaign(page: Page, browser: Browser) {
  const report = `Volt Typhoon targets edge routers ${Date.now()}`;
  await signIn(page, OWNER);
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(report);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  // Before the send there is no A/B result to show.
  await expect(page.getByTestId("ab-result")).toHaveCount(0);

  const session = await browser.newContext();
  const approverPage = await session.newPage();
  await signIn(approverPage, APPROVER);
  await approverPage.getByRole("button", { name: report }).click();
  await approverPage.getByRole("button", { name: "Approve" }).click();
  await expect(approverPage.getByTestId("run-status")).toHaveText("Sent");
  return { approverPage, session };
}

test.afterEach(async ({ page }) => {
  await setAudience(page, DEFAULT_SPEED);
});

test("a sent campaign says 'No decision yet' before the audience engages", async ({
  page,
  browser,
}) => {
  await setAudience(page, SLOW_SPEED);
  const { approverPage, session } = await sendCampaign(page, browser);

  await expect(approverPage.getByTestId("ab-result")).toHaveText("No decision yet");
  await session.close();
});

test("a sent campaign names the winner and its confidence once enough opens arrive", async ({
  page,
  browser,
}) => {
  await setAudience(page, DAY_SPEED);
  const { approverPage, session } = await sendCampaign(page, browser);

  await expect(approverPage.getByTestId("ab-result")).toHaveText(/^Winner: [AB] \(\d+% confident\)$/, {
    timeout: SETTLE_MS,
  });
  await session.close();
});
