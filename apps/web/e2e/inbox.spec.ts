import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, signIn } from "./fixtures/sign-in";

const DEFAULT_WORKFLOW = "threat-report-to-campaign";
// Four writers, each reviewed twice, take longer than a screen's default wait.
const RUN_WAIT_MS = 30_000;

// "[agent:flag]" makes the scripted brand reviewer flag every draft, so the inbox has flags to show.
test("an approver previews assets, sees the reviewer's flags, approves one and rejects another", async ({
  page,
  browser,
}) => {
  const title = `Asset review ${Date.now()}`;
  await signIn(page, OWNER);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.\n[agent:flag]`);
  await page.getByLabel("Workflow").fill(DEFAULT_WORKFLOW);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", {
    timeout: RUN_WAIT_MS,
  });

  const approverSession = await browser.newContext();
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("button", { name: "Inbox", exact: true }).click();

  const card = (step: string) => approver.getByRole("article", { name: `${title}: ${step}` });
  await expect(card("landing_page")).toBeVisible();
  await expect(card("email_writer")).toBeVisible();
  // The landing page shows its rendered preview and what the brand reviewer flagged.
  // Scoped to the card: other specs' runs share the inbox and have their own landing_page preview.
  const preview = card("landing_page").frameLocator('iframe[title="Preview of landing_page"]');
  await expect(preview.locator("body")).toContainText(title);
  await expect(card("landing_page").getByTestId("asset-flags")).toContainText("banned_claim");

  // Approve one asset with a comment: it leaves the inbox.
  await card("social").getByLabel("Comment").fill("Reads well");
  await card("social").getByRole("button", { name: "Approve" }).click();
  await expect(card("social")).toHaveCount(0);

  // Rejecting needs a comment. The asset goes back to its writer and returns when redone.
  await expect(card("landing_page").getByRole("button", { name: "Reject" })).toBeDisabled();
  await card("landing_page").getByLabel("Comment").fill("Drop the hype");
  await card("landing_page").getByRole("button", { name: "Reject" }).click();
  await expect(card("landing_page")).toBeVisible();
  // The other assets were not redone and are still waiting.
  await expect(card("one_pager")).toBeVisible();
  await expect(card("social")).toHaveCount(0);
  await approverSession.close();
});
