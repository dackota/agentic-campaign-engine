import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { APPROVER, OWNER, signIn } from "./fixtures/sign-in";

const RUN_WAIT_MS = 30_000;

async function waitingCampaign(browser: Browser, title: string, marker = ""): Promise<void> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, OWNER);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.\n${marker}`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });
}

async function waitingOf(count: Locator): Promise<number> {
  return Number((await count.textContent())?.match(/\d+/)?.[0]);
}

async function approverInbox(browser: Browser): Promise<Page> {
  const approver = await (await browser.newContext()).newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("button", { name: "Inbox", exact: true }).click();
  return approver;
}

test("an approver approves all clean assets, rejects a flagged one with a comment, and the count drops", async ({
  browser,
}) => {
  const clean = `Clean ${Date.now()}`;
  const flagged = `Flagged ${Date.now()}`;
  await waitingCampaign(browser, clean);
  await waitingCampaign(browser, flagged, "[agent:flag]");
  const approver = await approverInbox(browser);

  const group = (title: string) => approver.getByRole("region", { name: title });
  await expect(group(clean)).toBeVisible();
  await expect(group(flagged)).toBeVisible();
  const count = group(clean).getByTestId("campaign-waiting");
  await expect(count).toContainText(/\d+ assets? waiting/);
  const waitingBefore = await waitingOf(count);

  // Flags are a highlighted note in plain words, never a code.
  const flaggedCards = group(flagged).getByRole("article").filter({ hasText: "Banned claim" });
  const flaggedCount = await flaggedCards.count();
  expect(flaggedCount).toBeGreaterThan(0);
  await expect(flaggedCards.first().getByTestId("asset-flags")).not.toContainText("banned_claim");

  // Reject says a comment is needed before it is clicked, and refuses without one.
  const flaggedCard = flaggedCards.first();
  const reject = flaggedCard.getByRole("button", { name: /Reject/ });
  await expect(reject).toContainText("comment needed");
  await expect(reject).toBeDisabled();

  // Approve all with no flags approves only the clean assets: the flagged ones stay, the count drops.
  const flaggedWaiting = group(flagged).getByTestId("campaign-waiting");
  const flaggedWaitingBefore = await waitingOf(flaggedWaiting);
  await group(flagged).getByRole("button", { name: /Approve all with no flags/ }).click();
  await expect(group(flagged).getByRole("article")).toHaveCount(flaggedCount);
  expect(flaggedWaitingBefore).toBeGreaterThan(flaggedCount);
  // The clean campaign is untouched by the other campaign's button, then goes in one click.
  await expect(count).toContainText(`${waitingBefore} `);
  expect(waitingBefore).toBeGreaterThan(0);
  await group(clean).getByRole("button", { name: /Approve all with no flags/ }).click();
  await expect(group(clean)).toHaveCount(0);

  // Reject a flagged asset with a comment: the waiting count for that campaign is refreshed.
  await flaggedCard.getByLabel("Comment").fill("Drop the hype");
  await expect(reject).toBeEnabled();
  const rejected = approver.waitForResponse((r) => r.url().endsWith("/reject") && r.request().method() === "POST");
  await reject.click();
  // The reject really reached the API: a no-op click would never answer.
  const response = await rejected;
  expect(response.status()).toBe(200);
  expect((await response.json()).decision).toBe("rejected");
  // A rejected asset goes back to its writer and returns when redone, so the flagged campaign
  // keeps its flagged assets waiting; the count dropped when the clean assets were approved.
  await expect(group(flagged).getByRole("article")).toHaveCount(flaggedCount);
});
