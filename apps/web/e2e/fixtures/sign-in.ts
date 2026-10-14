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

/** Pick a saved workflow by its id in the new-campaign form. The picker reads the list when the
 * form opens, so a workflow saved since then needs the form reopened: go to the builder and back.
 * Call it before filling in the form, because reopening clears it. */
export async function chooseWorkflow(page: Page, id: string): Promise<void> {
  await page.getByRole("button", { name: "Workflow builder" }).click();
  await page.getByRole("button", { name: "Campaigns" }).click();
  await page.getByLabel("Workflow", { exact: true }).selectOption({ value: id });
}

/** Pick the built-in one-email pipeline, which shows the draft and its A/B result on the run page. */
export async function chooseQuickDraft(page: Page): Promise<void> {
  await page.getByLabel("Workflow", { exact: true }).selectOption({ label: "Quick email draft" });
}

/** The signed-in page's access token, for API calls a spec makes beside the screen. */
export async function accessTokenOf(page: Page): Promise<string> {
  const token = await page.evaluate(() => sessionStorage.getItem("ace.access_token"));
  if (!token) throw new Error("the page is not signed in");
  return token;
}
