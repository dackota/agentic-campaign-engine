import { expect, test, type Page } from "@playwright/test";
import { APPROVER, signIn } from "./fixtures/sign-in";

const TEAM = "demand-gen";
// The user menu summary and the five nav buttons: the shell's own tab stops (the page below varies with the data).
const FOCUS_STOPS = 6;
const VIEWPORT_HEIGHT_PX = 900;
const WIDTHS_PX = [1280, 768];
const PAGES = ["Campaigns", "Workflow builder", "Learnings", "Dashboard", "Inbox"];

/** The page does not scroll sideways and the header and every nav control sit inside the viewport. */
async function fitsViewport(page: Page, width: number) {
  const header = await page.getByRole("banner").boundingBox();
  expect(header, "the header is on the page").not.toBeNull();
  expect(header!.x + header!.width).toBeLessThanOrEqual(width);
  for (const button of await page.getByRole("navigation").getByRole("button").all()) {
    const box = await button.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the header shows product, team and user; sign-out is in the user menu", async ({ page }) => {
  await signIn(page, APPROVER);
  const header = page.getByRole("banner");
  await expect(header).toContainText("Agentic Campaign Engine");
  await expect(header.getByTestId("team")).toHaveText(TEAM);
  await expect(header.getByTestId("signed-in-as")).toHaveText(APPROVER);
  await header.getByTestId("signed-in-as").click();
  await header.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("the navigation marks the current page", async ({ page }) => {
  await signIn(page, APPROVER);
  const nav = page.getByRole("navigation");
  for (const name of PAGES) {
    await nav.getByRole("button", { name }).click();
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav.getByRole("button", { name })).toHaveAttribute("aria-current", "page");
  }
});

test("the shell works by keyboard with visible focus", async ({ page }) => {
  await signIn(page, APPROVER);
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
  await page.getByRole("button", { name: "Dashboard" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
  // The user menu opens and signs out by keyboard alone.
  await page.getByTestId("signed-in-as").focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("no horizontal scroll at 1280 and 768", async ({ page }) => {
  await signIn(page, APPROVER);
  for (const width of WIDTHS_PX) {
    await page.setViewportSize({ width, height: VIEWPORT_HEIGHT_PX });
    for (const name of PAGES) {
      await page.getByRole("navigation").getByRole("button", { name }).click();
      await fitsViewport(page, width);
    }
  }
});

test("the stylesheet defines the design tokens", async ({ page }) => {
  await page.goto("/");
  const tokens = await page.evaluate(() =>
    ["--color-primary", "--space-2", "--font-size-md", "--radius", "--shadow"].map((t) =>
      getComputedStyle(document.documentElement).getPropertyValue(t).trim(),
    ),
  );
  for (const value of tokens) expect(value).not.toBe("");
});
