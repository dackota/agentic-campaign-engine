import { expect, test } from "@playwright/test";

test("clicking Approve sends the email and shows the receipt", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Threat report").fill("Volt Typhoon targets edge routers");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  await expect(page.getByTestId("receipt")).toHaveCount(0);
  await page.getByRole("button", { name: "Approve" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Sent");
  await expect(page.getByTestId("receipt")).not.toBeEmpty();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
