import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, chooseQuickDraft, signIn } from "./fixtures/sign-in";

// A run to its approval takes seconds under load.
const RUN_WAIT_MS = 30_000;
const CAMPAIGN_URL = /\/campaigns\/[0-9a-f-]{36}$/;

// The one journey that needs the real stack: the live event stream, the second browser session,
// the send and the reload. Roles, labels and numbers on the page are proven by component tests.
test("an owner starts a campaign and watches it change, an approver sends it, and a reload still shows it sent", async ({
  page,
  browser,
}) => {
  const title = `Volt Typhoon targets edge routers ${Date.now()}`;
  await signIn(page, OWNER);
  await chooseQuickDraft(page);
  // [agent:slow] holds the agent's reply, so "Drafting" is on screen first.
  await page.getByLabel("Threat report").fill(`${title}\n[agent:slow]\nActors exploit unpatched VPN appliances.`);
  await page.evaluate(() => Object.assign(window, { stillTheFirstPageLoad: true }));
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page).toHaveURL(CAMPAIGN_URL);
  await expect(page.getByTestId("run-status")).toHaveText("Drafting");
  await expect(page.getByTestId("step-email_draft")).toContainText("Running");
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });
  await expect(page.getByTestId("step-email_draft")).toContainText("Done");
  // The status changed on the page itself: no reload happened.
  expect(await page.evaluate(() => "stillTheFirstPageLoad" in window)).toBe(true);
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  await expect(page.frameLocator('iframe[title="Email preview"]').locator("body")).toContainText("Volt Typhoon");

  const approverSession = await browser.newContext();
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("link", { name: title }).click();
  await approver.getByRole("button", { name: "Approve" }).click();
  await expect(approver.getByTestId("run-status")).toHaveText("Sent");
  await expect(approver.getByTestId("receipt")).not.toBeEmpty();

  const campaignUrl = approver.url();
  await approver.reload();
  await expect(approver).toHaveURL(campaignUrl);
  await expect(approver.getByTestId("run-status")).toHaveText("Sent");
  await expect(approver.getByTestId("receipt")).not.toBeEmpty();
  await approverSession.close();
});
