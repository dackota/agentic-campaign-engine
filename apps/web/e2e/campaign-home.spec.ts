import { expect, test, type Page } from "@playwright/test";
import { OWNER, PM_OWNER, VIEWER, chooseQuickDraft, openNewCampaign, signIn } from "./fixtures/sign-in";

const TABLET_WIDTH_PX = 768;
const TABLET_HEIGHT_PX = 900;
const CAMPAIGN_URL = /\/campaigns\/[0-9a-f-]{36}$/;

async function startCampaign(page: Page, title: string): Promise<void> {
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page).toHaveURL(CAMPAIGN_URL);
}

test("home shows a card per campaign with title, status, owner, start time and cost", async ({ page }) => {
  const title = `Card check ${Date.now()}`;
  await signIn(page, OWNER);
  await startCampaign(page, title);
  await page.getByRole("button", { name: "Campaigns" }).click();

  const card = page.getByRole("listitem").filter({ hasText: title });
  await expect(card.getByRole("link", { name: title })).toBeVisible();
  await expect(card.getByTestId("card-status")).not.toBeEmpty();
  await expect(card.getByTestId("card-owner")).toHaveText("You");
  await expect(card.getByTestId("card-started")).not.toBeEmpty();
  await expect(card.getByTestId("card-cost")).toHaveText(/^\$\d+\.\d\d$/);
});

test("an empty team sees a friendly empty state with a start button", async ({ page }) => {
  await signIn(page, PM_OWNER);
  await expect(page.getByText("No campaigns yet")).toBeVisible();
  await page.getByRole("link", { name: "Start your first campaign" }).click();
  await expect(page).toHaveURL(/\/campaigns\/new$/);
});

test("new campaign is its own page and the create button says why it is disabled", async ({ page }) => {
  await signIn(page, OWNER);
  await openNewCampaign(page);
  await expect(page).toHaveURL(/\/campaigns\/new$/);
  const create = page.getByRole("button", { name: "Create campaign" });
  await expect(create).toBeDisabled();
  await expect(page.getByText("Add your threat report to start the campaign.")).toBeVisible();
  await expect(page.getByText("The campaign pauses if it reaches this amount")).toBeVisible();
  await page.getByLabel("Threat report").fill("Something happened");
  await expect(create).toBeEnabled();
  await expect(page.getByText("Add your threat report to start the campaign.")).toHaveCount(0);
});

test("an owner starts a campaign from home and lands on its own URL; reload shows it", async ({ page }) => {
  await signIn(page, OWNER);
  await startCampaign(page, `Own URL ${Date.now()}`);
  const url = page.url();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  const subject = await page.getByTestId("draft-subject").innerText();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(page.getByTestId("draft-subject")).toHaveText(subject);
});

test("a viewer sees no New campaign button", async ({ page, browser }) => {
  const ownerSession = await browser.newContext();
  const ownerPage = await ownerSession.newPage();
  await signIn(ownerPage, OWNER);
  await expect(ownerPage.getByRole("link", { name: "New campaign" })).toBeVisible();
  await signIn(page, VIEWER);
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByRole("link", { name: "New campaign" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Start your first campaign" })).toHaveCount(0);
  await ownerSession.close();
});

test("home has no horizontal scroll at 768", async ({ page }) => {
  await signIn(page, OWNER);
  await startCampaign(page, `Narrow ${Date.now()}`);
  await page.getByRole("button", { name: "Campaigns" }).click();
  await page.setViewportSize({ width: TABLET_WIDTH_PX, height: TABLET_HEIGHT_PX });
  await expect(page.getByTestId("card-status").first()).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
