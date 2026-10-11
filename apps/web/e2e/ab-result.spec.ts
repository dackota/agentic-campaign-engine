import { expect, test } from "@playwright/test";
import { APPROVER, OWNER, signIn } from "./fixtures/sign-in";

test("a sent campaign shows the A/B result: a winner with confidence, or no decision yet", async ({
  page,
  browser,
}) => {
  const report = `Volt Typhoon targets edge routers ${Date.now()}`;
  await signIn(page, OWNER);
  await page.getByLabel("Threat report").fill(report);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  // Before the send there is no A/B result to show.
  await expect(page.getByTestId("ab-result")).toHaveCount(0);

  const approverSession = await browser.newContext();
  const approverPage = await approverSession.newPage();
  await signIn(approverPage, APPROVER);
  await approverPage.getByRole("button", { name: report }).click();
  await approverPage.getByRole("button", { name: "Approve" }).click();
  await expect(approverPage.getByTestId("run-status")).toHaveText("Sent");

  await expect(approverPage.getByTestId("ab-result")).toHaveText(
    /No decision yet|Winner: [AB] \(\d+% confident\)/,
  );
  await approverSession.close();
});
