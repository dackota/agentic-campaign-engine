import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { APPROVER, accessTokenOf, signIn, chooseQuickDraft, openNewCampaign } from "./fixtures/sign-in";

test("the approval screen shows the rendered email", async ({ page }) => {
  await signIn(page);
  await chooseQuickDraft(page);
  await page.getByLabel("Threat report").fill("Volt Typhoon targets edge routers");
  await page.getByRole("button", { name: "Create campaign" }).click();

  await expect(page.getByTestId("draft-subject")).not.toBeEmpty();
  const preview = page.frameLocator('iframe[title="Email preview"]');
  await expect(preview.locator("img").first()).toHaveAttribute("alt", /.+/);
  await expect(preview.locator("body")).toContainText("Volt Typhoon");
});

/** One inbox card's preview: painted, its logo and images loaded, at full size. */
async function expectPreviewShown(card: Locator, step: string): Promise<void> {
  const frame = await card.locator("iframe").elementHandle();
  const doc = await frame?.contentFrame();
  expect(doc, `${step} has a preview frame`).toBeTruthy();
  // A blank preview paints no text and no image: measure the document, SVG or HTML.
  await expect
    .poll(
      () =>
        doc!.evaluate(() => {
          const root = document.documentElement;
          const painted = (root.textContent ?? "").trim().length > 0 || root.querySelector("img") !== null;
          return painted && root.getBoundingClientRect().height > 0;
        }),
      { message: `${step} preview is blank` },
    )
    .toBe(true);
  const broken = await doc!.evaluate(
    () => [...document.images].filter((i) => !i.complete || i.naturalWidth === 0).length,
  );
  expect(broken, `${step} has a broken image`).toBe(0);
  // Every preview carries the brand logo: an img (HTML) or an image (SVG) that loaded.
  const logo = await doc!.evaluate(() => {
    const img = document.querySelector<HTMLImageElement>('img[alt$="logo"]');
    if (img) return img.naturalWidth;
    const svgImage = document.querySelector("svg image");
    return svgImage ? svgImage.getBoundingClientRect().width : 0;
  });
  expect(logo, `${step} shows the brand logo`).toBeGreaterThan(0);
  // The frame has its full size at the demo's viewport, without scrolling to it first.
  const box = await card.locator("iframe").evaluate((f) => ({
    w: f.clientWidth,
    h: f.clientHeight,
    shown: getComputedStyle(f).visibility === "visible" && getComputedStyle(f).display !== "none",
  }));
  expect(box.shown).toBe(true);
  expect(box.h).toBeGreaterThanOrEqual(300);
  expect(box.w).toBeGreaterThan(600);
}

test.use({ viewport: { width: 1280, height: 720 } });

test("every inbox asset preview has visible content and no broken image", async ({ page, browser }) => {
  const title = `Preview check ${Date.now()}`;
  await signIn(page);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: 30_000 });
  const approverSession = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  await approver.getByRole("button", { name: "Inbox", exact: true }).click();

  for (const step of ["Landing page", "Social post", "One-pager", "Email", "Design"]) {
    const card = approver.getByRole("article", { name: `${title}: ${step}` });
    await expect(card).toBeVisible();
    await expectPreviewShown(card, step);
  }
  await approverSession.close();
});

const MIN_PAINTED_PNG_BYTES = 4_000;
// Tall enough that every frame of the linked campaign is in view at first paint: the browser
// throttles a sandboxed frame that is off screen and paints it only once scrolled to.
const ALL_FRAMES_HEIGHT_PX = 3600;
const VIEWPORTS = [
  { name: "laptop", width: 1280, height: ALL_FRAMES_HEIGHT_PX },
  { name: "tablet", width: 768, height: ALL_FRAMES_HEIGHT_PX },
];
const LANDING_PREVIEW = "**/api/campaigns/*/preview/landing-page*";
const PREVIEW_DELAY_MS = 2_000;

/** A campaign waiting for approval, opened in an approver's inbox through the campaign link, so
 * its assets come first however many others wait in the shared inbox. `beforeOpen` sets up the page. */
async function openWaitingCampaign(
  { page, browser }: { page: Page; browser: Browser },
  title: string,
  viewport: { width: number; height: number },
  beforeOpen: (approver: Page) => Promise<void> = async () => {},
): Promise<Page> {
  await signIn(page);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: 30_000 });
  const approver = await (await browser.newContext({ viewport })).newPage();
  await signIn(approver, APPROVER);
  const inbox = await approver.request.get("/api/inbox", {
    headers: { authorization: `Bearer ${await accessTokenOf(approver)}` },
  });
  const mine = ((await inbox.json()) as { campaign_id: string; title: string }[]).find((a) => a.title === title);
  await beforeOpen(approver);
  await approver.goto(`/?inbox=${mine?.campaign_id}`);
  return approver;
}

for (const viewport of VIEWPORTS) {
  test(`every inbox preview paints visible pixels on first view at ${viewport.name} width`, async ({ page, browser }) => {
    const title = `Pixel check ${Date.now()}`;
    const approver = await openWaitingCampaign({ page, browser }, title, viewport);
    for (const step of ["Landing page", "Social post", "One-pager", "Email", "Design"]) {
      const frame = approver.getByRole("article", { name: `${title}: ${step}` }).locator("iframe");
      // No scrolling to the frame and no wait beyond its load.
      await expect(frame).toHaveAttribute("data-loaded", "true");
      const shot = await approver.screenshot({ clip: (await frame.boundingBox()) ?? undefined });
      expect(shot.length, `${step} preview is blank on first view`).toBeGreaterThan(MIN_PAINTED_PNG_BYTES);
    }
  });
}

test("a preview shows Loading preview until its frame loads", async ({ page, browser }) => {
  const title = `Loading note ${Date.now()}`;
  const approver = await openWaitingCampaign({ page, browser }, title, VIEWPORTS[0]!, async (a) => {
    await a.route(LANDING_PREVIEW, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, PREVIEW_DELAY_MS));
      await route.continue();
    });
  });
  const card = approver.getByRole("article", { name: `${title}: Landing page` });
  const note = card.getByRole("status");
  // The shared LoadingBlock, with the ellipsis character the rest of the app uses.
  await expect(note).toHaveText("Loading preview…");
  await expect(note).toHaveClass(/block-loading/);
  await expect(card.locator("iframe")).toHaveAttribute("data-loaded", "true");
  await expect(note).toHaveCount(0);
});

test("a preview that cannot load says what to do", async ({ page, browser }) => {
  const title = `Failed preview ${Date.now()}`;
  const approver = await openWaitingCampaign({ page, browser }, title, VIEWPORTS[0]!, async (a) => {
    await a.route(LANDING_PREVIEW, (route) => route.fulfill({ status: 500, body: "boom" }));
  });
  const alert = approver.getByRole("article", { name: `${title}: Landing page` }).getByRole("alert");
  await expect(alert).toHaveText("This preview could not be loaded. Reload the page to try again.");
  await expect(alert).toHaveClass(/block-error/);
});
