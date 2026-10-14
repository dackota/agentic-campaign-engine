import { expect, type Page } from "@playwright/test";

// Demo users from platform/dex/config.yaml; the password is demo-only.
export const OWNER = "dg-owner@demo.example";
export const APPROVER = "dg-approver@demo.example";
const DEMO_PASSWORD = "demo-password";

/** Sign in through Dex's login page, the way a marketer does. */
export async function signIn(page: Page, email: string = OWNER): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Email Address").fill(email);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page.getByTestId("signed-in-as")).toHaveText(email);
}

/** Open the new-campaign page from home. Safe to call when it is already open. */
export async function openNewCampaign(page: Page): Promise<void> {
  if (await page.getByLabel("Threat report").count()) return;
  await page.getByRole("link", { name: /New campaign|Start your first campaign/ }).first().click();
  await expect(page.getByLabel("Threat report")).toBeVisible();
}

/** Pick the built-in one-email pipeline, which shows the draft and its A/B result on the run page. */
export async function chooseQuickDraft(page: Page): Promise<void> {
  await openNewCampaign(page);
  await page.getByLabel("Workflow", { exact: true }).selectOption({ label: "Quick email draft" });
}

/** The signed-in page's access token, for API calls a spec makes beside the screen. */
export async function accessTokenOf(page: Page): Promise<string> {
  const token = await page.evaluate(() => sessionStorage.getItem("ace.access_token"));
  if (!token) throw new Error("the page is not signed in");
  return token;
}
