import { expect, test } from "@playwright/test";
import { OWNER, signIn } from "./fixtures/sign-in";

// Only a real browser and the real Dex prove the redirect round trip. What each screen shows
// for its data is proven by the component tests beside the screens.
test("a marketer signs in through Dex, sees the campaign list, and signs out", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Campaigns" })).toHaveCount(0);

  await signIn(page, OWNER);

  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  // A team with no campaigns sees the empty state instead of the list.
  await expect(
    page.getByRole("list", { name: "Campaigns" }).or(page.getByText("No campaigns yet")),
  ).toBeVisible();

  await page.getByTestId("signed-in-as").click();
  await page.getByRole("banner").getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
