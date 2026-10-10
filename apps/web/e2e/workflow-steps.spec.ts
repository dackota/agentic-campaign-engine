import { expect, test } from "@playwright/test";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("run view lists the DAG steps in order", async ({ page, request }) => {
  const name = `e2e-steps-${Date.now()}`;
  const saved = await request.post(`/api/workflows/${name}/versions`, {
    data: {
      steps: [
        { id: "publish", kind: "publish" },
        { id: "approve", kind: "approval" },
        { id: "writer", kind: "agent" },
        { id: "preview", kind: "render" },
      ],
      edges: [
        { from: "writer", to: "preview" },
        { from: "preview", to: "approve" },
        { from: "approve", to: "publish" },
      ],
    },
  });
  expect(saved.status()).toBe(201);

  await page.goto("/");
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByLabel("Workflow").fill(name);
  await page.getByRole("button", { name: "Create campaign" }).click();

  const steps = page.getByRole("list", { name: "Run steps" }).getByRole("listitem");
  await expect(steps).toHaveText([/^writer/, /^preview/, /^approve/, /^publish/]);
  await expect(page.getByTestId("step-writer")).toContainText("succeeded");
  await expect(page.getByTestId("step-publish")).toContainText("pending");
});

test("the default workflow lists its steps before they run", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Threat report").fill(REPORT);
  await page.getByRole("button", { name: "Create campaign" }).click();

  const steps = page.getByRole("list", { name: "Run steps" }).getByRole("listitem");
  await expect(steps).toHaveText([/^Email draft/, /^approval/, /^publish/]);
});
