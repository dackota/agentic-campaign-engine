import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("step status changes on the page without a reload", async ({ page }) => {
  await signIn(page);
  // [agent:slow] makes the scripted agent hold its reply, so "started" is on screen first.
  await page.getByLabel("Threat report").fill(`[agent:slow]\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  const step = page.getByTestId("step-email_draft");
  await expect(step).toContainText("started");
  await expect(step).toContainText("succeeded");
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
});

test("bad agent output shows failed and the reason", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("Threat report").fill(`[agent:bad-json]\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("step-email_draft")).toContainText("failed");
  await expect(page.getByRole("alert")).toContainText("contract");
  await expect(page.getByTestId("draft-subject")).toHaveCount(0);
});
