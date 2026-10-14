import { expect, test } from "@playwright/test";
import { OWNER, signIn, openNewCampaign } from "./fixtures/sign-in";

test("signing in through Dex shows the campaign list", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Campaigns" })).toHaveCount(0);

  await signIn(page, OWNER);

  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  // A team with no campaigns sees the empty state instead of the list.
  await expect(
    page.getByRole("list", { name: "Campaigns" }).or(page.getByText("No campaigns yet")),
  ).toBeVisible();
});

test("a campaign the owner creates shows in the list", async ({ page }) => {
  const report = `Volt Typhoon targets edge routers ${Date.now()}`;
  await signIn(page, OWNER);

  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(report);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page).toHaveURL(/\/campaigns\/[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "Campaigns" }).click();

  await expect(page.getByRole("list", { name: "Campaigns" })).toContainText(report);
});
