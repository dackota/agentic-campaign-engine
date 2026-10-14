import { expect, test } from "@playwright/test";
import { accessTokenOf, chooseWorkflow, signIn, chooseQuickDraft } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

// "[agent:usage-IN-OUT]" makes the scripted agent report that usage on every reply. At the
// default list price ($3 and $15 per million tokens), 1200 in and 300 out cost $0.0081.
test("the run view shows tokens and cost per step and in total", async ({ page }) => {
  await signIn(page);
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill(`[agent:usage-1200-300]\n${REPORT}\n${Date.now()}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval");
  // The main screen shows dollars and cents; tokens and exact cost sit behind Details.
  await expect(page.getByTestId("run-cost")).toHaveText("$0.02");
  await page.getByRole("button", { name: "Details" }).click();
  // The email draft step makes two replies: the A/B variants.
  await expect(page.getByTestId("step-cost-email_draft")).toHaveText("3,000 tokens, $0.0162");
  // The judge step makes one reply: 1500 tokens, $0.0081.
  await expect(page.getByTestId("step-cost-judge")).toHaveText("1,500 tokens, $0.0081");
  await expect(page.getByTestId("run-tokens")).toHaveText("4,500 tokens, $0.0243");
});

test("a run paused at its budget resumes when the owner raises it", async ({
  page,
  request,
}) => {
  const name = `e2e-budget-${Date.now()}`;
  await signIn(page);
  const saved = await request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: {
      steps: [
        { id: "first", kind: "agent" },
        { id: "second", kind: "agent" },
      ],
      edges: [{ from: "first", to: "second" }],
    },
  });
  expect(saved.status()).toBe(201);

  await chooseWorkflow(page, name);
  await page.getByLabel("Threat report").fill(`[agent:usage-1000-500]\n${REPORT}\n${name}`);
  await page.getByLabel("Budget (USD)").fill("0.01");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Paused at budget");
  await expect(page.getByTestId("step-second")).toContainText("pending");
  await page.getByLabel("New budget (USD)").fill("1");
  await page.getByRole("button", { name: "Raise budget" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Finished");
  await expect(page.getByTestId("step-second")).toContainText("succeeded");
  await expect(page.getByTestId("run-cost")).toHaveText("$0.04");
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByTestId("run-tokens")).toHaveText("6,000 tokens, $0.0420");
});
