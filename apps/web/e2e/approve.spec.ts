import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, signIn } from "./fixtures/sign-in";

test("an approver approves the owner's campaign and sees the receipt", async ({
  page,
  browser,
}) => {
  const report = `Volt Typhoon targets edge routers ${Date.now()}`;
  await signIn(page, OWNER);
  await page.getByLabel("Threat report").fill(report);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  // The owner cannot approve their own campaign, so the screen offers no Approve button.
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);

  const approverSession = await browser.newContext();
  const approverPage = await approverSession.newPage();
  await signIn(approverPage, APPROVER);
  await approverPage.getByRole("button", { name: report }).click();
  await expect(approverPage.getByTestId("draft-subject")).not.toBeEmpty();
  await expect(approverPage.getByTestId("receipt")).toHaveCount(0);
  await approverPage.getByRole("button", { name: "Approve" }).click();

  await expect(approverPage.getByTestId("run-status")).toHaveText("Sent");
  await expect(approverPage.getByTestId("receipt")).not.toBeEmpty();
  await expect(approverPage.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await approverSession.close();
});
