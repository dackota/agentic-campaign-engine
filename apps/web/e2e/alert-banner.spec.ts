import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

// The harness stack takes this token from the environment (playwright.config.ts).
const ALERT_TOKEN = process.env.ACE_ALERT_WEBHOOK_TOKEN ?? "";

function grafanaAlert(name: string, status: "firing" | "resolved", summary: string) {
  return {
    receiver: "ace-api",
    alerts: [
      {
        status,
        labels: { alertname: name },
        annotations: { summary },
        startsAt: "2026-10-11T10:00:00Z",
        endsAt: status === "firing" ? "0001-01-01T00:00:00Z" : "2026-10-11T10:05:00Z",
        fingerprint: `fp-${name}`,
      },
    ],
  };
}

test("the banner shows a fired alert and drops it when it resolves", async ({ page, request }) => {
  const name = `gateway-failover-${Date.now()}`;
  await signIn(page);
  await expect(page.getByTestId("alert-banner")).toHaveCount(0);

  const fired = await request.post("/api/alerts/webhook", {
    headers: { authorization: `Bearer ${ALERT_TOKEN}` },
    data: grafanaAlert(name, "firing", "Model calls failed over to the backup provider"),
  });
  expect(fired.status()).toBe(202);

  await expect(page.getByTestId("alert-banner")).toContainText(name);
  await expect(page.getByTestId("alert-banner")).toContainText(
    "Model calls failed over to the backup provider",
  );

  const resolved = await request.post("/api/alerts/webhook", {
    headers: { authorization: `Bearer ${ALERT_TOKEN}` },
    data: grafanaAlert(name, "resolved", "Model calls failed over to the backup provider"),
  });
  expect(resolved.status()).toBe(202);
  await expect(page.getByTestId("alert-banner")).toHaveCount(0);
});
