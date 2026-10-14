# Go-public check

One run of `bash scripts/go-public-check.sh` on branch `impl/63-prep`. Counts below are for that run, made with land/ace commit 49857e5 merged in; they drift as base moves, so run it again before going public. It exits 0 when clean, 1 when the secret scan fails, 2 when only brand hits or flagged licenses remain. Its brand scan skips `scripts/go-public-check.sh` and this file, since both name the deny list, so every count below excludes both.

Nothing was changed to remove a brand, no LICENSE was added, no history was rewritten, and repo visibility was not touched.

## Result of the run

Exit code 1: the secret scan failed on 2 findings, both false positives (below).

## Secret scan

gitleaks over every commit of every ref, redacted. Result: FAIL, 2 findings (counts and locations only, no values).

| Rule | File:line | Commit |
|---|---|---|
| generic-api-key | evals/README.md:23 | 701a82f94b7c |
| generic-api-key | docs/learning-proof.md:11 | 701a82f94b7c |

Both lines are the same shell example that sets the owner and approver API token variables to angle-bracket placeholders, then the depth variable to `live`. They are placeholders, not secrets. (This file describes the line instead of quoting it, because quoting it makes gitleaks flag this file too.) Triage by the hand: false positive. The script does not suppress them, so it keeps failing until the user decides how to allowlist them (for example a `.gitleaksignore` entry) or rewords the two lines.

## Brand hits

Deny list: CrowdStrike, Adobe, Marketo, Workfront, Salesforce, Palo Alto, Okta, Microsoft, Google, Slack, Figma. 881 hit lines in tracked files. Chosen because each appears in the repo, and the first six all appear in the REAL_BRANDS ban list of tests/tooling/test_demo_script.py, along with Microsoft, Google and Slack. Stack tools (kagent, Temporal, Postgres, and so on) are not on the list.

Real company names outside an integration, with file:line:

- SPEC.md:226 (Okta, Entra, as examples of a company IdP)
- platform/dex/config.yaml:1 (Okta, Entra, same)
- tests/api/snapshots/email_preview.html:1 (Microsoft, an XML namespace in generated email HTML)
- tests/tooling/test_demo_script.py:18 to :24 (CrowdStrike, Palo Alto, Microsoft, Salesforce, Adobe in the ban list of the script test)

Brand names used as integration names (fakes, MCP servers, settings, tests, charts, docs): Marketo 379 lines, Workfront 250, Slack 129, Google 124, Figma 28. The script lists every one with file:line. Heaviest files by brand-line count: tests/harness/stack.py 86, test_env_settings.py 54, api/helpers.py 42, the engine settings.py 38, tooling test_chart_app.py 27, test_integration_settings.py 26.

## Licenses

Direct dependencies: Python from `pyproject.toml` (installed metadata), JS from `apps/web/package.json` (installed `node_modules` metadata, falling back to the latest published license from npm when a package is not installed). 29 checked, 1 flagged.

- Flagged: psycopg, LGPL-3.0-only. It is linked as a library, not modified; LGPL allows that. The script flags every copyleft license for a human to decide.
- Everything else is MIT, BSD, or Apache-2.0.

## Open items for the user

- The repo license: there is no LICENSE file. Pick one before going public.
- Brand names used as integration names: the fake Marketo and Workfront servers and MCP tools, plus the Slack, Google, and Figma integrations. SPEC.md says no real brand appears in the repo, so decide whether these count or are accepted as integration names.
- The 2 secret-scan false positives above: allowlist or reword.
- The psycopg LGPL note above: accept or swap.
- Okta and Entra mentions in SPEC.md:226 and platform/dex/config.yaml:1.
