import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { APPROVER, accessTokenOf, openNewCampaign, signIn } from "./fixtures/sign-in";

const RUN_WAIT_MS = 30_000;
const STEPS = ["Landing page", "Social post", "One-pager", "Email", "Design"];
const MIN_PAINTED_PNG_BYTES = 4_000;
// Tall enough that every frame of the linked campaign is in view at first paint: the browser
// throttles a sandboxed frame that is off screen and paints it only once scrolled to.
const ALL_FRAMES_HEIGHT_PX = 3600;
const VIEWPORTS = [
  { name: "laptop", width: 1280, height: ALL_FRAMES_HEIGHT_PX },
  { name: "tablet", width: 768, height: ALL_FRAMES_HEIGHT_PX },
];

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
  // The frame has its full size at this viewport, without scrolling to it first.
  const box = await card.locator("iframe").evaluate((f) => ({
    w: f.clientWidth,
    h: f.clientHeight,
    shown: getComputedStyle(f).visibility === "visible" && getComputedStyle(f).display !== "none",
  }));
  expect(box.shown).toBe(true);
  expect(box.h).toBeGreaterThanOrEqual(300);
  expect(box.w).toBeGreaterThan(600);
}

/** An approver's inbox opened through the campaign link, so its assets come first however many others wait. */
async function openInboxFor(browser: Browser, title: string, viewport: { width: number; height: number }): Promise<Page> {
  const approver = await (await browser.newContext({ viewport })).newPage();
  await signIn(approver, APPROVER);
  const inbox = await approver.request.get("/api/inbox", {
    headers: { authorization: `Bearer ${await accessTokenOf(approver)}` },
  });
  const mine = ((await inbox.json()) as { campaign_id: string; title: string }[]).find((a) => a.title === title);
  await approver.goto(`/?inbox=${mine?.campaign_id}`);
  return approver;
}

// Painting, image loading and the logo are real-browser facts that jsdom cannot show. What the
// frame says while loading or when it fails is a component test (PreviewFrame.test.tsx).
test("every inbox asset preview paints visible pixels, shows the brand logo and has no broken image", async ({
  page,
  browser,
}) => {
  const title = `Pixel check ${Date.now()}`;
  await signIn(page);
  await openNewCampaign(page);
  await page.getByLabel("Threat report").fill(`${title}\nActors exploit unpatched VPN appliances.`);
  await page.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });

  for (const viewport of VIEWPORTS) {
    const approver = await openInboxFor(browser, title, viewport);
    for (const step of STEPS) {
      const card = approver.getByRole("article", { name: `${title}: ${step}` });
      const frame = card.locator("iframe");
      // No scrolling to the frame and no wait beyond its load.
      await expect(frame).toHaveAttribute("data-loaded", "true");
      const shot = await approver.screenshot({ clip: (await frame.boundingBox()) ?? undefined });
      expect(shot.length, `${step} preview is blank on first view at ${viewport.name} width`).toBeGreaterThan(
        MIN_PAINTED_PNG_BYTES,
      );
      await expectPreviewShown(card, step);
    }
    await approver.context().close();
  }
});
