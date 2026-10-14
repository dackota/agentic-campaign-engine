import { expect, test, type Locator } from "@playwright/test";
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

test("every inbox preview paints visible pixels on first view", async ({ page, browser }) => {
  const title = `Pixel check ${Date.now()}`;
  await signIn(page);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: 30_000 });
  const approverSession = await browser.newContext({ viewport: { width: 1280, height: ALL_FRAMES_HEIGHT_PX } });
  const approver = await approverSession.newPage();
  await signIn(approver, APPROVER);
  // The campaign link puts this campaign's assets first, however many others wait in the shared inbox.
  const inbox = await approver.request.get("/api/inbox", {
    headers: { authorization: `Bearer ${await accessTokenOf(approver)}` },
  });
  const mine = ((await inbox.json()) as { campaign_id: string; title: string }[]).find((a) => a.title === title);
  await approver.goto(`/?inbox=${mine?.campaign_id}`);

  const steps = ["Landing page", "Social post", "One-pager", "Email", "Design"];
  for (const step of steps) {
    const frame = approver.getByRole("article", { name: `${title}: ${step}` }).locator("iframe");
    // No scrolling to the frame and no wait beyond its load.
    await expect(frame).toHaveAttribute("data-loaded", "true");
    const box = await frame.boundingBox();
    const shot = await approver.screenshot({ clip: box ?? undefined });
    expect(shot.length, `${step} preview is blank on first view`).toBeGreaterThan(MIN_PAINTED_PNG_BYTES);
  }
  await approverSession.close();
});

const MIN_PAINTED_PNG_BYTES = 4_000;
// Tall enough that every frame of the linked campaign is on screen at once, so none waits below the fold to be painted.
const ALL_FRAMES_HEIGHT_PX = 3200;
