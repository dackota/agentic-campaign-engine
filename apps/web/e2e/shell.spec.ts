import { expect, test, type Page } from "@playwright/test";
import { APPROVER, signIn } from "./fixtures/sign-in";

const PAGES = ["Campaigns", "Workflow builder", "Learnings", "Dashboard", "Inbox"];

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the header shows product, team and user; sign-out is in the user menu", async ({ page }) => {
  await signIn(page, APPROVER);
  const header = page.getByRole("banner");
  await expect(header).toContainText("Agentic Campaign Engine");
  await expect(header.getByTestId("team")).toBeVisible();
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
  for (let i = 0; i < 12; i++) {
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
});

test("no horizontal scroll at 1280 and 768", async ({ page }) => {
  await signIn(page, APPROVER);
  for (const width of [1280, 768]) {
    await page.setViewportSize({ width, height: 900 });
    for (const name of PAGES) {
      await page.getByRole("navigation").getByRole("button", { name }).click();
      await noHorizontalScroll(page);
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
