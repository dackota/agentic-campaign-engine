import { workflowLabel } from "../src/labels.ts";
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

async function openBuilder(page: Page) {
  await signIn(page);
  await page.getByRole("button", { name: "Workflow builder" }).click();
}
const stepList = (page: Page) => page.getByRole("list", { name: "Workflow steps" }).getByRole("listitem");

test("opens on a template gallery with no error, and a palette that explains each step", async ({ page }) => {
  await openBuilder(page);
  await expect(page.getByRole("button", { name: "Use template: Threat report to campaign" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start a blank workflow" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);

  await page.getByRole("button", { name: "Start a blank workflow" }).click();
  const palette = page.getByRole("list", { name: "Step palette" }).getByRole("listitem");
  await expect(palette).toHaveCount(5);
  await expect(palette.filter({ hasText: "Approval" })).toContainText("A person says yes");
  await expect(page.getByText("Add at least one step")).toBeVisible();
});

test("shows a plain message next to the step it is about", async ({ page }) => {
  await openBuilder(page);
  await page.getByRole("button", { name: "Start a blank workflow" }).click();
  await page.getByRole("button", { name: "Add Approval" }).click();
  await expect(stepList(page).first()).toContainText("An approval step needs a step before it");
  await expect(page.getByRole("button", { name: "Save version" })).toBeDisabled();

  await page.getByRole("button", { name: "Add Publish" }).click();
  await expect(stepList(page).nth(1)).toContainText("needs an AI step before it");
});

test("moves a step with the mouse and with the keyboard", async ({ page }) => {
  await openBuilder(page);
  await page.getByRole("button", { name: "Use template: Threat report to campaign" }).click();
  const steps = stepList(page);
  await expect(steps).toHaveText([/Email draft/, /Approval/, /Publish/]);

  await steps.nth(2).dragTo(steps.nth(1));
  await expect(steps).toHaveText([/Email draft/, /Publish/, /Approval/]);

  await page.getByRole("button", { name: "Move Approval" }).focus();
  await page.keyboard.press("ArrowUp");
  await expect(steps).toHaveText([/Email draft/, /Approval/, /Publish/]);
  await expect(page.getByRole("button", { name: "Move Approval" })).toBeFocused();
});

test("starts from the template, moves a step, adds an approval step, saves, and runs", async ({ page }) => {
  const name = `e2e-build-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await openBuilder(page);
  await page.getByRole("button", { name: "Use template: Threat report to campaign" }).click();
  const steps = stepList(page);
  await expect(steps).toHaveCount(3);

  // Break it: the approval step moves last, so publish has none before it.
  await page.getByRole("button", { name: "Move Approval" }).focus();
  await page.keyboard.press("ArrowDown");
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
  await page.getByLabel("Workflow", { exact: true }).selectOption({ value: name });
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("workflow-version")).toHaveText(`${workflowLabel(name)} version 1`);
});
