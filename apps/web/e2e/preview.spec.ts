import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

test("the approval screen shows the rendered email", async ({ page }) => {
  await signIn(page);
  await page.getByLabel("Threat report").fill("Volt Typhoon targets edge routers");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  const preview = page.frameLocator('iframe[title="Email preview"]');
  await expect(preview.locator("img").first()).toHaveAttribute("alt", /.+/);
  await expect(preview.locator("body")).toContainText("Volt Typhoon");
});
