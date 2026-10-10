import { expect, test } from "@playwright/test";

test("the approval screen shows the rendered email", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Threat report").fill("Volt Typhoon targets edge routers");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  const preview = page.frameLocator('iframe[title="Email preview"]');
  await expect(preview.locator("img").first()).toHaveAttribute("alt", /.+/);
  await expect(preview.locator("body")).toContainText("Volt Typhoon");
});
