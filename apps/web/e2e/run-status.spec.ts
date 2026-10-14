import { expect, test } from "@playwright/test";
import { signIn, chooseQuickDraft } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("step status changes on the page without a reload", async ({ page }) => {
  await signIn(page);
  // [agent:slow] makes the scripted agent hold its reply, so "started" is on screen first.
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(`[agent:slow]\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  const step = page.getByTestId("step-email_draft");
  await expect(step).toContainText("Running");
  await expect(step).toContainText("Done");
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
});

test("bad agent output shows failed and the reason", async ({ page }) => {
  await signIn(page);
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(`[agent:bad-json]\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("step-email_draft")).toContainText("Failed");
  await expect(page.getByRole("alert")).toHaveText(/^The .+ step did not finish\.$/);
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByTestId("failure-raw")).toContainText("contract");
  await expect(page.getByTestId("draft-subject")).toHaveCount(0);
});
