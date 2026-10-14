import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";

// A plain script, not a test: it drives the browser with the Playwright library and records a video.
// scripts/record-demo.sh starts the stack, sets the ports below, and runs this. The beats follow
// docs/demo-script.md. Each caption stays on screen while its beat plays.
const APPROVER = "dg-approver@demo.example";
const OWNER = "dg-owner@demo.example";
const PM_OWNER = "pm-owner@demo.example";
const REPORT = readFileSync(resolve(import.meta.dirname, "../../../docs/demo-report.txt"), "utf8").trim();
const TITLE = REPORT.split("\n")[0];
const FAILING_TITLE = "Acme Security: a fake supplier invoice page";
const BUDGET_TITLE = "Acme Security: a lost laptop alert";
const DEMO_PASSWORD = "demo-password";
const marketoPort = process.env.ACE_MARKETO_PORT;
if (!marketoPort) throw new Error("ACE_MARKETO_PORT is unset: run through scripts/record-demo.sh");
const AUDIENCE_URL = `http://127.0.0.1:${marketoPort}/_audience`;
// Days of simulated opens and clicks arrive in seconds, so the A/B test calls a winner on camera.
const DAY_SPEED = 100_000;
const DEFAULT_SPEED = 86_400;
const RUN_WAIT_MS = 60_000;
const READ_MS = 3_500;
const CAPTION_PREFIX = "demo-caption:";

// window.name survives navigation, also to Dex and back, so the caption is drawn again on each page.
function drawCaption(prefix) {
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

async function caption(page, text) {
  await page.evaluate(
    ([prefix, t]) => {
      window.name = prefix + t;
    },
    [CAPTION_PREFIX, text],
  );
  await page.evaluate(drawCaption, CAPTION_PREFIX);
}

// One caption per beat of docs/demo-script.md, numbered so a frame says which beat it shows.
const BEAT_COUNT = 10;
const beat = (page, n, text) => caption(page, `${n}/${BEAT_COUNT}  ${text}`);

const mustBe = (ok, message) => {
  if (!ok) throw new Error(message);
};

// Waits until the element's whole text is `text` (a string) or matches it (a regex).
const shows = (locator, text) =>
  locator
    .filter({ hasText: typeof text === "string" ? new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`) : text })
    .waitFor({ timeout: RUN_WAIT_MS });

// The signed-in page's access token, for API calls beside the screen.
async function accessTokenOf(page) {
  const token = await page.evaluate(() => sessionStorage.getItem("ace.access_token"));
  mustBe(token, "the page is not signed in");
  return token;
}

const hold = (page, ms = READ_MS) => page.waitForTimeout(ms);

// Centred, so the caption bar at the bottom never hides what the beat is about.
async function centre(locator) {
  await locator.evaluate((el) => el.scrollIntoView({ block: "center" }));
}

async function show(page, label) {
  await centre(page.getByLabel(label, { exact: true }).first());
  await hold(page);
}

async function signOut(page) {
  await page.getByTestId("signed-in-as").click();
  await page.getByRole("button", { name: "Sign out" }).click();
}

async function signIn(page, email) {
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Email Address").pressSequentially(email, { delay: 30 });
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();
  await shows(page.getByTestId("signed-in-as"), email);
}


const FAILING_REPORT = "Acme Security: a fake supplier invoice page\nCriminals send invoices that look real.\n[agent:down-2]";
const BUDGET_REPORT = "Acme Security: a lost laptop alert\nLost laptops carry customer files.\n[agent:usage-1000-500]";

// A saved workflow of two steps; the first fails twice (both attempts), the rest is kept on retry.
async function saveWorkflow(page, name, steps, edges) {
  const saved = await page.request.post(`/api/workflows/${name}/versions`, {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: { steps, edges },
  });
  mustBe(saved.status() === 201, `saving ${name} returned ${saved.status()}`);
}

async function startViaApi(page, report, workflow, budget) {
  const created = await page.request.post("/api/campaigns", {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: { report, workflow, ...(budget === undefined ? {} : { budget_usd: budget }) },
  });
  mustBe(created.status() < 300, `starting a campaign returned ${created.status()}`);
}

// The list reads the API when the page loads, so reload to pick up a campaign started on the side.
const openFromList = async (page, title) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Campaigns" }).click();
  await page.getByRole("link", { name: title }).click();
};

async function problem(page) {
  await page.goto("/");
  await beat(page, 1, "A threat report used to mean a week of hand-offs. Acme Security (made up) does it in minutes.");
  await hold(page);
  await signIn(page, OWNER);
  await page.getByRole("heading", { name: "Campaigns" }).waitFor({ timeout: RUN_WAIT_MS });
  await hold(page);
}

async function startCampaign(page) {
  await page.getByRole("link", { name: "New campaign" }).first().click();
  await beat(page, 2, "The owner pastes a threat report, sets a spending limit if wanted, and presses Create campaign.");
  await page.getByLabel("Threat report").pressSequentially(REPORT, { delay: 8 });
  await page.getByLabel("Budget (USD)").fill("5");
  await centre(page.getByRole("button", { name: "Create campaign" }));
  await hold(page, 1_500);
  await page.getByRole("button", { name: "Create campaign" }).click();
}

// Both runs go on in the background while the owner watches the main campaign.
async function startSideRuns(page) {
  await saveWorkflow(
    page,
    "quick-email-with-retry",
    [
      { id: "email_draft", kind: "agent", retry: { maximum_attempts: 2, initial_interval_seconds: 0.1 } },
      { id: "preview", kind: "render" },
    ],
    [{ from: "email_draft", to: "preview" }],
  );
  await saveWorkflow(
    page,
    "two-step-email",
    [
      { id: "email_draft", kind: "agent" },
      { id: "judge", kind: "agent" },
    ],
    [{ from: "email_draft", to: "judge" }],
  );
  await startViaApi(page, FAILING_REPORT, "quick-email-with-retry");
  await startViaApi(page, BUDGET_REPORT, "two-step-email", 0.01);
}

async function helpersWork(page) {
  await beat(page, 3, "AI helpers work in parallel, and you see each step light up as it runs.");
  await show(page, "Run steps");
  await openFromList(page, FAILING_TITLE);
  await page.getByRole("button", { name: "Retry step" }).waitFor({ timeout: RUN_WAIT_MS });
  await beat(page, 3, "If a step fails, the finished work is kept, and one click tries that step again.");
  await hold(page);
  await page.getByRole("button", { name: "Retry step" }).click();
  await shows(page.getByTestId("run-status"), "Finished");
  await beat(page, 3, "The step ran again, and the campaign finished.");
  await hold(page);
  await openFromList(page, TITLE);
  await shows(page.getByTestId("run-status"), "Waiting for approval");
}

async function realAssets(page) {
  await beat(page, 4, "Helpers read the team's own systems, then make a real email, landing page, one-pager, deck, and social cards.");
  await show(page, "Draft");
  await signOut(page);
  await signIn(page, APPROVER);
  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  await page.getByRole("article", { name: `${TITLE}: Landing page` }).waitFor({ timeout: RUN_WAIT_MS });
  await hold(page);
}

async function judgeScores(page) {
  await beat(page, 5, "A judge scores every asset against written brand rules before a person reads it.");
  await centre(page.getByRole("article", { name: `${TITLE}: Email` }));
  await hold(page);
}

async function approve(page) {
  await beat(page, 6, "The person who asked cannot approve. The team's approver reviews every asset and approves.");
  await page.getByRole("button", { name: "Approve all with no flags" }).first().click();
  await hold(page);
  await openFromList(page, TITLE);
  const approveButton = page.getByRole("button", { name: "Approve" });
  if (await approveButton.count()) {
    await centre(approveButton);
    await hold(page, 1_500);
    await approveButton.click();
  }
  await shows(page.getByTestId("run-status"), "Sent");
  await centre(page.getByTestId("run-status"));
  await beat(page, 6, "Sent. The page, the email and the team note went out, and a receipt is kept.");
  await hold(page);
}

async function results(page) {
  await beat(page, 7, "Two email versions go out. The system counts opens and clicks and names a winner.");
  await shows(page.getByTestId("ab-result"), /^Version [AB] won/);
  await centre(page.getByTestId("ab-result"));
  await hold(page);
  await page.getByRole("button", { name: "Learnings" }).click();
  await beat(page, 7, "The result becomes a learning that the helpers read on the next campaign.");
  await hold(page);
  await page.getByRole("button", { name: "Dashboard" }).click();
  await beat(page, 7, "The team dashboard tracks cost, quality, and click rate for every campaign.");
  await hold(page);
}

async function cost(page) {
  await openFromList(page, TITLE);
  await beat(page, 8, "Every step shows what it cost. Finished work is reused, not paid for twice.");
  await centre(page.getByTestId("run-cost"));
  await hold(page);
  await signOut(page);
  await signIn(page, OWNER);
  await openFromList(page, BUDGET_TITLE);
  await shows(page.getByTestId("run-status"), "Paused at budget");
  await beat(page, 8, "A campaign that hits its limit pauses and asks. The owner raises the budget, and it goes on.");
  await hold(page);
  await page.getByLabel("New budget (USD)").fill("1");
  await page.getByRole("button", { name: "Raise budget" }).click();
  await shows(page.getByTestId("run-status"), "Finished");
  await hold(page);
}

async function builder(page) {
  await page.getByRole("button", { name: "Workflow builder" }).click();
  await beat(page, 9, "A marketer starts from a template, drags steps into a new order, and adds an approval step.");
  await page.getByRole("button", { name: "Use template: Threat report to campaign" }).click();
  const steps = page.getByRole("list", { name: "Workflow steps" }).getByRole("listitem");
  await hold(page);
  await page.getByRole("button", { name: "Add Approval" }).click();
  await steps.last().dragTo(steps.nth(1));
  await centre(page.getByRole("list", { name: "Step palette" }));
  await hold(page);
}

async function manyTeams(page) {
  await signOut(page);
  await signIn(page, PM_OWNER);
  await beat(page, 10, "Product Marketing uses the same system and sees only its own campaigns. Every change is tested first.");
  await hold(page);
  await beat(page, 10, "One report in. Drafted, judged, approved, sent, measured, and remembered.");
  await hold(page);
}

async function setAudience(page, timeSpeed) {
  const response = await page.request.put(AUDIENCE_URL, { data: { seed: 1, time_speed: timeSpeed } });
  mustBe(response.status() === 204, `steering the audience returned ${response.status()}`);
}


async function main() {
  const webPort = process.env.ACE_WEB_PORT;
  mustBe(webPort, "ACE_WEB_PORT is unset: run through scripts/record-demo.sh");
  const outDir = process.env.ACE_DEMO_VIDEO_DIR;
  mustBe(outDir, "ACE_DEMO_VIDEO_DIR is unset: run through scripts/record-demo.sh");
  const browser = await chromium.launch({ slowMo: 120 });
  const context = await browser.newContext({
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: outDir, size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(RUN_WAIT_MS);
  await page.addInitScript(drawCaption, CAPTION_PREFIX);
  // The receipt reference is an opaque generated id, so it stays out of every frame.
  await page.addInitScript(() => {
    const hide = () => {
      const style = document.createElement("style");
      style.textContent = '[data-testid="receipt"] { visibility: hidden; }';
      document.head.append(style);
    };
    document.addEventListener("DOMContentLoaded", hide, { once: true });
  });
  try {
    await setAudience(page, DAY_SPEED);
    await problem(page);
    await startCampaign(page);
    await startSideRuns(page);
    await helpersWork(page);
    await realAssets(page);
    await judgeScores(page);
    await approve(page);
    await results(page);
    await cost(page);
    await builder(page);
    await manyTeams(page);
  } finally {
    await setAudience(page, DEFAULT_SPEED).catch((error) => console.error("could not reset the audience speed:", error));
    await context.close(); // writes the video
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
