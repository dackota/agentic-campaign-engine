import { expect, test, type Page } from "@playwright/test";
import { accessTokenOf, signIn } from "./fixtures/sign-in";

const REPORT = "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.";
const WIDTHS = [
  { name: "laptop", width: 1280, height: 800 },
  { name: "tablet", width: 820, height: 1180 },
];

async function saveParallelWorkflow(page: Page, name: string): Promise<void> {
  const saved = await page.request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: {
      steps: [
        { id: "brief", kind: "agent" },
        { id: "writer_a", kind: "agent" },
        { id: "writer_b", kind: "agent", retry: { maximum_attempts: 2, initial_interval_seconds: 0.1 } },
        { id: "preview", kind: "render" },
      ],
      edges: [
        { from: "brief", to: "writer_a" },
        { from: "brief", to: "writer_b" },
        { from: "writer_a", to: "preview" },
        { from: "writer_b", to: "preview" },
      ],
    },
  });
  expect(saved.status()).toBe(201);
}

for (const size of WIDTHS) {
  test(`run graph shows live status, retries, tokens and overlap to the end at ${size.name} width`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: size.width, height: size.height });
    const name = `e2e-graph-${size.name}-${Date.now()}`;
    await signIn(page);
    await saveParallelWorkflow(page, name);

    // [agent:down-1] fails the first agent call, so one step retries once.
    await page.getByLabel("Threat report").fill(`[agent:down-1]\n${REPORT}\n${name}`);
    await page.getByLabel("Workflow").fill(name);
    await page.getByRole("button", { name: "Create campaign" }).click();

    const graph = page.getByTestId("run-graph");
    await expect(graph).toBeVisible();
    for (const id of ["brief", "writer_a", "writer_b", "preview"]) {
      await expect(page.getByTestId(`step-${id}`)).toBeVisible();
    }
    // Edges are drawn: one line per DAG edge.
    await expect(graph.locator("[data-edge]")).toHaveCount(4);

    // The run finishes; every step shows its final status without a reload.
    await expect(page.getByTestId("run-status")).toHaveText("Finished");
    for (const id of ["brief", "writer_a", "writer_b", "preview"]) {
      await expect(page.getByTestId(`step-${id}`)).toContainText("succeeded");
    }
    await expect(page.getByTestId("step-brief")).toContainText(/\d+ tokens/);
    await expect(page.getByTestId("step-writer_a")).toContainText("alongside writer_b");
    await expect(page.getByTestId("step-writer_b")).toContainText("alongside writer_a");
    await expect(page.getByTestId("step-brief")).not.toContainText("alongside");
    // The brief took the failed first call, so it ran twice.
    await expect(page.getByTestId("step-brief")).toContainText("1 retry");
    await expect(page.getByTestId("step-writer_a")).not.toContainText("retry");

    // The graph fits the page: nothing makes the page scroll sideways.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `test-results/run-graph-${size.name}.png`, fullPage: true });
  });
}
