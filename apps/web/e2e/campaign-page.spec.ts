import { expect, test } from "@playwright/test";
import { VIEWER, accessTokenOf, chooseQuickDraft, chooseWorkflow, signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("the page goes from Drafting to Waiting for approval with a next-step sentence, no reload", async ({
  page,
}) => {
  await signIn(page);
  await chooseQuickDraft(page);
  // [agent:slow] holds the agent's reply, so "Drafting" is on screen first.
  await page.getByLabel("Threat report").fill(`[agent:slow]\n${REPORT}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("[agent:slow]");
  await expect(page.getByTestId("run-status")).toHaveText("Drafting");
  await expect(page.getByTestId("next-step")).toHaveText("The AI is writing the draft.");
  await expect(page.getByTestId("step-email_draft")).toContainText("Running");

  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval");
  await expect(page.getByTestId("next-step")).toHaveText("Waiting for an approver.");
  await expect(page.getByTestId("step-email_draft")).toContainText("Done");
});

test("quality, cost and draft show as cards with the rendered email", async ({ page }) => {
  await signIn(page);
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval");
  for (const name of ["Quality", "Cost", "Draft"]) {
    await expect(page.getByRole("region", { name })).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "Cost" }).getByTestId("run-cost")).toBeVisible();
  const preview = page.frameLocator('iframe[title="Email preview"]');
  await expect(preview.locator("body")).toContainText("Volt Typhoon");
  await expect(page.locator('iframe[title="Email preview"]')).toHaveAttribute("sandbox", "");

  await page.setViewportSize({ width: 768, height: 1024 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a failed step shows its reason in plain words, the owner can retry, a viewer cannot", async ({
  page,
  browser,
}) => {
  const name = `e2e-page-${Date.now()}`;
  await signIn(page);
  const saved = await page.request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: {
      steps: [
        { id: "writer", kind: "agent", retry: { maximum_attempts: 2, initial_interval_seconds: 0.1 } },
        { id: "preview", kind: "render" },
      ],
      edges: [{ from: "writer", to: "preview" }],
    },
  });
  expect(saved.status()).toBe(201);
  await chooseWorkflow(page, name);
  await page.getByLabel("Threat report").fill(`[agent:down-2]\n${REPORT}\n${name}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Failed");
  await expect(page.getByTestId("step-writer")).toContainText("Failed");
  await expect(page.getByTestId("next-step")).toContainText("retry");
  await expect(page.getByRole("alert")).toContainText("2 attempts");

  const session = await browser.newContext();
  const viewerPage = await session.newPage();
  await signIn(viewerPage, VIEWER);
  await viewerPage.goto(new URL(page.url()).pathname);
  await expect(viewerPage.getByTestId("run-status")).toHaveText("Failed");
  await expect(viewerPage.getByRole("button", { name: "Retry step" })).toHaveCount(0);
  await session.close();

  await page.getByRole("button", { name: "Retry step" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Finished");
  await expect(page.getByTestId("step-writer")).toContainText("Done");
});
