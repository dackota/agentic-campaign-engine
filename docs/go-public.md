# Go-public check

Run `bash scripts/go-public-check.sh` from the repo root before the repo goes public. It exits 0 when clean, 1 when the secret scan fails, 2 when only brand hits or flagged licenses remain. Its output holds the live numbers and every file:line. This file holds none of them, because they go stale on every merge.

The brand scan skips `scripts/go-public-check.sh` and this file, since both name the deny list.

## Decisions

- **License:** MIT. See `LICENSE`.
- **Brand names:** the deny list is CrowdStrike, Adobe, Marketo, Workfront, Salesforce, Palo Alto, Okta, Microsoft, Google, Slack, Figma. Marketo, Workfront, Slack, Google and Figma stay as the names of the integrations the demo fakes. SPEC.md says so. The script keeps listing them; read its output as a list to review, not a failure.
- **Okta and Entra:** the example mentions in SPEC.md and `platform/dex/config.yaml` stay. They name company identity providers as examples.
- **psycopg (LGPL-3.0-only):** accepted. It is linked as a library and not modified, which LGPL allows. The script flags every copyleft license for a human to decide.

## Secret scan

gitleaks over every commit of every ref, redacted. The only findings were two false positives: the same shell example in `evals/README.md` and `docs/learning-proof.md` sets API token variables to angle-bracket placeholders. They are allowlisted by fingerprint in `.gitleaksignore`, so the scan passes. (This file describes the line instead of quoting it, because quoting it makes gitleaks flag this file too.)

## Brand hits

The script prints `file:line:word` for every tracked line that holds a deny-list word, never the line itself. Real company names outside an integration, to check by hand:

- SPEC.md and `platform/dex/config.yaml` (Okta, Entra, as examples of a company IdP)
- `tests/api/snapshots/email_preview.html` (Microsoft, an XML namespace in generated email HTML)
- `tests/tooling/test_demo_script.py` (the ban list of the script test)

If the brand scan itself cannot read a tracked file, it prints `brand scan: FAIL` and never PASS.

## Licenses

Direct dependencies: Python from `pyproject.toml` (installed metadata), JS from `apps/web/package.json` (installed `node_modules` metadata, falling back to the latest published license from npm). Everything but psycopg is MIT, BSD, MPL, or Apache-2.0. Any license text with a control byte is flagged.

## Open items

None for the check. The nightly k3d run and the PR eval gate need standard runners, so they are built after the repo is public (#63).
