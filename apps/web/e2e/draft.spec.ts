import { expect, test } from "@playwright/test";
import { signIn, chooseQuickDraft } from "./fixtures/sign-in";

test("pasting a threat report shows the email draft", async ({ page }) => {
  await signIn(page);
  await chooseQuickDraft(page);
  await page
    .getByLabel("Threat report")
    .fill("Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  await expect(page.getByTestId("draft-body")).toContainText("Volt Typhoon");
});
