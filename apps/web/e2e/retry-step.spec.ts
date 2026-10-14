import { expect, test } from "@playwright/test";
import { accessTokenOf, chooseWorkflow, signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";

test("a failed run shows a retry-step action that resumes it to the end", async ({
  page,
  request,
}) => {
  const name = `e2e-retry-${Date.now()}`;
  await signIn(page);
  const saved = await request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: {
      steps: [
        {
          id: "writer",
          kind: "agent",
          retry: { maximum_attempts: 2, initial_interval_seconds: 0.1 },
        },
        { id: "preview", kind: "render" },
      ],
      edges: [{ from: "writer", to: "preview" }],
    },
  });
  expect(saved.status()).toBe(201);

  // [agent:down-2] makes the scripted agent fail the first two calls: both attempts.
  await chooseWorkflow(page, name);
  await page.getByLabel("Threat report").fill(`[agent:down-2]\n${REPORT}\n${name}`);
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("step-writer")).toContainText("Failed");
  await expect(page.getByRole("alert")).toContainText("2 attempts");
  await page.getByRole("button", { name: "Retry step" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Finished");
  await expect(page.getByTestId("step-writer")).toContainText("Done");
  await expect(page.getByTestId("step-preview")).toContainText("Done");
  await expect(page.getByRole("button", { name: "Retry step" })).toHaveCount(0);
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
});
