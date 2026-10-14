import { expect, test, type Page } from "@playwright/test";
import { APPROVER, OWNER, accessTokenOf, signIn } from "./fixtures/sign-in";

const RUN_WAIT_MS = 30_000;
const VIEWPORT_HEIGHT_PX = 900;
const WIDTHS_PX = [1280, 768];
const TABLET_WIDTH_PX = 768;
const PAGES = ["Campaigns", "Workflow builder", "Learnings", "Dashboard", "Inbox"];
// The user menu summary and the five nav buttons: the shell's own tab stops (the page below varies with the data).
const FOCUS_STOPS = 6;

/** The page does not scroll sideways and the header and every nav control sit inside the viewport. */
async function fitsViewport(page: Page, width: number) {
  const header = await page.getByRole("banner").boundingBox();
  expect(header, "the header is on the page").not.toBeNull();
  expect(header!.x + header!.width).toBeLessThanOrEqual(width);
  for (const button of await page.getByRole("navigation").getByRole("button").all()) {
    const box = await button.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  }
  await expectNoSidewaysScroll(page);
}

async function expectNoSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** An owner's campaign through the API, so the campaign page has a run graph to lay out. */
async function startCampaign(page: Page): Promise<string> {
  const created = await page.request.post("/api/campaigns", {
    headers: { authorization: `Bearer ${await accessTokenOf(page)}` },
    data: { report: `Layout check ${Date.now()}\nActors exploit unpatched VPN appliances.` },
  });
  expect(created.ok()).toBe(true);
  return ((await created.json()) as { id: string }).id;
}

// Sideways scroll, wrapping and focus outlines are layout and style facts that only a real browser
// computes. What the pages say is proven by the component tests.
test("no page scrolls sideways at 1280 and 768, the run graph wraps, and focus rings show", async ({
  page,
  browser,
}) => {
  const ownerSession = await browser.newContext();
  const owner = await ownerSession.newPage();
  await signIn(owner, OWNER);
  const campaignId = await startCampaign(owner);
  await ownerSession.close();
  await signIn(page, APPROVER);
  // Measure a finished draft: cards fill in while the run is still drafting, and move the layout.
  await page.goto(`/campaigns/${campaignId}`);
  await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval", { timeout: RUN_WAIT_MS });

  for (const width of WIDTHS_PX) {
    await page.setViewportSize({ width, height: VIEWPORT_HEIGHT_PX });
    for (const name of PAGES) {
      await page.getByRole("navigation").getByRole("button", { name }).click();
      await fitsViewport(page, width);
    }
    await page.goto(`/campaigns/${campaignId}`);
    await expect(page.getByTestId("run-status")).toHaveText("Waiting for approval");
    await fitsViewport(page, width);
  }

  // At tablet width the graph wraps: no inner scroll, and every step sits inside the viewport.
  const graph = await page.locator(".run-graph-scroll").evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(graph).toBeLessThanOrEqual(0);
  for (const step of await page.getByRole("list", { name: "Run steps" }).getByRole("listitem").all()) {
    await expect(step).toBeVisible();
    const box = await step.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(TABLET_WIDTH_PX);
  }

  await page.locator("body").click({ position: { x: 0, y: 0 } });
  await page.keyboard.press("Tab");
  for (let i = 0; i < FOCUS_STOPS; i++) {
    const outline = await page.evaluate(() => {
      const s = getComputedStyle(document.activeElement as Element);
      return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
    });
    expect(outline.style).not.toBe("none");
    expect(outline.width).toBeGreaterThan(0);
    await page.keyboard.press("Tab");
  }
});
