import { workflowLabel } from "../src/labels.ts";
import { expect, test } from "@playwright/test";
import { signIn, openNewCampaign } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

// Dragging, the focus after a keyboard move, saving to the API and running the saved version
// need a real browser and the real stack. The builder's messages and move logic are component tests.
test("starts from the template, moves a step, adds an approval step, saves, and runs", async ({ page }) => {
  const name = `e2e-build-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await signIn(page);
  await page.getByRole("button", { name: "Workflow builder" }).click();
  await page.getByRole("button", { name: "Use template: Threat report to campaign" }).click();
  const steps = page.getByRole("list", { name: "Workflow steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(3);

  // Break it: the approval step moves last, so publish has none before it. The handle keeps the focus.
  await page.getByRole("button", { name: "Move Approval" }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Move Approval" })).toBeFocused();
  await expect(steps.nth(1)).toContainText("needs an approval step before it");
  await expect(page.getByRole("button", { name: "Save version" })).toBeDisabled();

  // Fix it with a second approval step, dragged above publish.
  await page.getByRole("button", { name: "Add Approval" }).click();
  await expect(steps).toHaveCount(4);
  await steps.nth(3).dragTo(steps.nth(1));
  await expect(page.getByText("needs an approval step before it")).toHaveCount(0);

  await steps.nth(0).getByLabel("Retry attempts").fill("4");

  await page.getByLabel("Workflow name").fill(name);
  await page.getByRole("button", { name: "Save version" }).click();
  await expect(page.getByRole("list", { name: "Saved versions" })).toContainText("Version 1");

  await page.getByRole("button", { name: "Campaigns" }).click();
  await openNewCampaign(page);
  await page.getByLabel("Workflow", { exact: true }).selectOption({ value: name });
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("workflow-version")).toHaveText(`${workflowLabel(name)} version 1`);
});
