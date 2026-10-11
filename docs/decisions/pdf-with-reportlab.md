# Decision: reportlab renders the PDF one-pager (S7, #42)

Date: 2026-10-11. Status: accepted.

Decision: the one-pager PDF is built with **reportlab**, not a headless browser. The root
`SPEC.md` Render row names "MJML, Playwright, python-pptx"; this keeps MJML for email and
python-pptx for the deck, and swaps Playwright for reportlab for the PDF only. The
`SPEC.md` row is unchanged.

## Why

- Same content gives the same bytes (`invariant=1`), so the preview route can be
  snapshot-tested and a second GET returns identical output.
- No browser binary in the API image, no extra process, no render timeout to manage.
- The one-pager is a title, a summary, and a bullet list. It needs no CSS layout.

## Cost

- The PDF layout is code, not HTML and CSS, so a designer cannot change it with the landing
  page template. If the one-pager needs rich layout, revisit and render HTML through
  Playwright.
