import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, signIn, openNewCampaign } from "./fixtures/sign-in";

const RUN_WAIT_MS = 30_000;
const RAW = ["email_writer", "one_pager", "tokens"];

test("the new-campaign form picks a workflow by name, defaulting to Threat report to campaign", async ({
  page,
}) => {
  await signIn(page, OWNER);
  await openNewCampaign(page);
  const picker = page.getByLabel("Workflow");
  await expect(picker.locator("option:checked")).toHaveText("Threat report to campaign");
  await expect(picker.locator("option", { hasText: "threat-report-to-campaign" })).toHaveCount(0);
});

test("the run page and the inbox show no raw ids or token counts, and Details shows them", async ({
  page,
  browser,
}) => {
  const title = `Plain words ${Date.now()}`;
  await signIn(page, OWNER);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });

  const main = page.locator("main");
  await expect(main).toContainText("One-pager");
  await expect(main).toContainText(/\$\d+\.\d\d(?!\d)/);
  for (const raw of RAW) await expect(main).not.toContainText(raw);

  await page.getByRole("button", { name: "Details" }).click();
  await expect(main).toContainText("tokens");
  await expect(main).toContainText("email_writer");

  const approverSession = await browser.newContext();
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("button", { name: "Inbox", exact: true }).click();
  await expect(approver.getByRole("article", { name: `${title}: One-pager` })).toBeVisible();
  for (const raw of RAW) await expect(approver.locator("main")).not.toContainText(raw);
  await approverSession.close();
});
