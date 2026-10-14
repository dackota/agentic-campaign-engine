import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { APPROVER, OWNER } from "../e2e/fixtures/sign-in";

// The beats follow docs/demo-script.md. Each caption stays on screen while its beat plays.
const REPORT = readFileSync(resolve(import.meta.dirname, "../../../docs/demo-report.txt"), "utf8").trim();
const TITLE = REPORT.split("\n")[0];
const DEMO_PASSWORD = "demo-password";
const marketoPort = process.env.ACE_MARKETO_PORT;
if (!marketoPort) throw new Error("ACE_MARKETO_PORT is unset: run through demo.config.ts");
const AUDIENCE_URL = `http://127.0.0.1:${marketoPort}/_audience`;
// Days of simulated opens and clicks arrive in seconds, so the A/B test calls a winner on camera.
const DAY_SPEED = 100_000;
const DEFAULT_SPEED = 86_400;
const RUN_WAIT_MS = 60_000;
const READ_MS = 3_500;
const CAPTION_PREFIX = "demo-caption:";

// window.name survives navigation, also to Dex and back, so the caption is drawn again on each page.
function drawCaption(prefix: string): void {
  if (!window.name.startsWith(prefix)) return;
  if (!document.body) {
    document.addEventListener("DOMContentLoaded", () => drawCaption(prefix), { once: true });
    return;
  }
  let bar = document.getElementById("demo-caption");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "demo-caption";
    bar.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:16px 32px;pointer-events:none;" +
      "background:rgba(17,24,39,.9);color:#fff;font:600 22px/1.4 system-ui,sans-serif;text-align:center";
    document.body.append(bar);
    // Room under the last line, so it can scroll up above the bar.
    document.body.style.paddingBottom = "50vh";
  }
  bar.textContent = window.name.slice(prefix.length);
}

async function caption(page: Page, text: string): Promise<void> {
  await page.evaluate(
    ([prefix, t]) => {
      window.name = prefix + t;
    },
    [CAPTION_PREFIX, text],
  );
  await page.evaluate(drawCaption, CAPTION_PREFIX);
}

const hold = (page: Page, ms = READ_MS) => page.waitForTimeout(ms);

// Centred, so the caption bar at the bottom never hides what the beat is about.
async function centre(locator: Locator): Promise<void> {
  await locator.evaluate((el) => el.scrollIntoView({ block: "center" }));
}

async function show(page: Page, label: string): Promise<void> {
  await centre(page.getByLabel(label, { exact: true }).first());
  await hold(page);
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Email Address").pressSequentially(email, { delay: 30 });
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page.getByTestId("signed-in-as")).toHaveText(email);
}

async function startCampaign(page: Page): Promise<void> {
  await page.goto("/");
  await caption(page, "Acme Security (made up) turns one threat report into a campaign, with people in charge.");
  await hold(page);
  await signIn(page, OWNER);
  await caption(page, "The marketer pastes a threat report and presses Create campaign.");
  await page.getByLabel("Threat report").pressSequentially(REPORT, { delay: 8 });
  await page.getByRole("button", { name: "Create campaign" }).click();
}

async function watchRun(page: Page): Promise<void> {
  await caption(page, "AI agents run the steps: draft, judge, approval, publish. Each step's cost is shown.");
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });
  await show(page, "Run steps");
  await show(page, "Run cost");
  await caption(page, "A judge agent scores the email against written rules before any person reads it.");
  await show(page, "Judge scores");
  await show(page, "Email draft");
  await caption(page, "The person who asked cannot approve their own campaign. An approver must.");
  await centre(page.getByTestId("run-status"));
  await hold(page);
}

async function approve(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await caption(page, "The team's approver signs in, opens the campaign, and approves it.");
  await signIn(page, APPROVER);
  await page.getByRole("button", { name: TITLE }).click();
  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  const approveButton = page.getByRole("button", { name: "Approve" });
  await centre(approveButton);
  await hold(page, 1_500);
  await approveButton.click();
  await expect(page.getByTestId("run-status")).toHaveText("Sent", { timeout: RUN_WAIT_MS });
  await centre(page.getByTestId("receipt"));
  await caption(page, "Sent. The receipt is the proof of what went out.");
  await hold(page);
}

async function results(page: Page): Promise<void> {
  await caption(page, "Two email versions go to the audience. The system counts opens and clicks and calls a winner.");
  await expect(page.getByTestId("ab-result")).toHaveText(/^Winner: [AB]/, { timeout: RUN_WAIT_MS });
  await centre(page.getByTestId("ab-result"));
  await hold(page);
  await page.getByRole("button", { name: "Learnings" }).click();
  await caption(page, "The result becomes a learning that the agents read on the next campaign.");
  await hold(page);
  await page.getByRole("button", { name: "Dashboard" }).click();
  await caption(page, "The dashboard tracks cost, quality, and click rate for each campaign.");
  await hold(page);
  await caption(page, "One report in. Drafted, judged, approved, sent, measured, and remembered.");
  await hold(page);
}

async function setAudience(page: Page, timeSpeed: number): Promise<void> {
  const response = await page.request.put(AUDIENCE_URL, { data: { seed: 1, time_speed: timeSpeed } });
  expect(response.status()).toBe(204);
}

test("record the demo", async ({ page }) => {
  await page.addInitScript(drawCaption, CAPTION_PREFIX);
  await setAudience(page, DAY_SPEED);
  try {
    await startCampaign(page);
    await watchRun(page);
    await approve(page);
    await results(page);
  } finally {
    await setAudience(page, DEFAULT_SPEED);
  }
});
