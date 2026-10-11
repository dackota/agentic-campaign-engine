import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("builds, breaks, fixes, saves, and runs a workflow", async ({ page }) => {
  const name = `e2e-build-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await signIn(page);
  await page.getByRole("button", { name: "Workflow builder" }).click();

  // Start from the default template.
  await page.getByRole("button", { name: "Use template: Threat report to campaign" }).click();
  const steps = page.getByRole("list", { name: "Workflow steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(3);

  // Add a wait step, then remove it.
  await page.getByRole("button", { name: "Add wait step" }).click();
  await expect(steps).toHaveCount(4);
  await steps.nth(3).getByRole("button", { name: "Remove" }).click();
  await expect(steps).toHaveCount(3);

  // Per-step policy on the agent step.
  await steps.nth(0).getByLabel("Retry attempts").fill("4");
  await steps.nth(0).getByLabel("Review rounds").fill("2");

  // Break it: remove the approval gate. A plain-language error shows and save is off.
  await steps.nth(1).getByRole("button", { name: "Remove" }).click();
  await expect(steps).toHaveCount(2);
  await expect(page.getByRole("alert")).toContainText("needs an approval step before it");
  await expect(page.getByRole("button", { name: "Save version" })).toBeDisabled();

  // Fix it: add a gate (it lands last), then drag it above publish.
  await page.getByRole("button", { name: "Add approval gate" }).click();
  await expect(page.getByRole("alert")).toContainText("needs an approval step before it");
  await steps.nth(2).dragTo(steps.nth(1));
  await expect(steps).toHaveText([/email_draft/, /approval/, /publish/]);
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.getByLabel("Workflow name").fill(name);
  await page.getByRole("button", { name: "Save version" }).click();
  await expect(page.getByRole("list", { name: "Saved versions" })).toContainText("Version 1");

  // Run it.
  await page.getByRole("button", { name: "Campaigns" }).click();
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByLabel("Workflow", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("workflow-version")).toHaveText(`${name} version 1`);
});
