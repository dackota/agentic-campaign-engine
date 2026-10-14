import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, signIn, openNewCampaign } from "./fixtures/sign-in";

const RUN_WAIT_MS = 30_000;

// The scripted judge scores every asset; the run view and the approval inbox show each one.
test("the run view and the inbox show each asset's judge score and reason", async ({ page, browser }) => {
  const title = `Judge scores ${Date.now()}`;
  await signIn(page, OWNER);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });

  const runScore = page.getByTestId("judge-score-landing_page");
  await expect(runScore).toContainText("/5");
  await expect(page.getByTestId("judge-reason-landing_page")).not.toBeEmpty();

  const approverSession = await browser.newContext();
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("button", { name: "Inbox", exact: true }).click();
  const card = approver.getByRole("article", { name: `${title}: Landing page` });
  await expect(card.getByTestId("asset-score")).toContainText("/5");
  await expect(card.getByTestId("asset-score-reason")).not.toBeEmpty();
  await approverSession.close();
});
