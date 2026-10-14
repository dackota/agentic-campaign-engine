#!/usr/bin/env bash
# Go-public check, run from inside the repo before the repo is made public:
#   1. gitleaks over every commit of every ref, redacted. Never prints a secret value.
#   2. every tracked line that names a real company or product brand (deny list below).
#   3. the license of each direct Python dependency (installed metadata) and JS dependency
#      (node_modules, else the latest published license from npm); GPL, AGPL, LGPL, unknown flagged.
# Exit 0: all clean. Exit 1: secret scan failed (or gitleaks could not run). Exit 2: secrets
# clean but brand hits or flagged licenses exist. Reads no .env and prints no env.
# The brand scan skips scripts/go-public-check.sh and docs/go-public.md: both name the deny
# list on purpose, so they would report themselves.
# Usage: go-public-check.sh [--classify "<license text>"]   (prints ok or flagged)
set -uo pipefail

BRANDS=(CrowdStrike Adobe Marketo Workfront Salesforce "Palo Alto" Okta Microsoft Google Slack Figma)
BRAND_SKIP=(scripts/go-public-check.sh docs/go-public.md)
# Allow list: a term is ok only when the whole term is a known permissive license name.
PERMISSIVE_TERM='(osi approved :: )?(mit|isc|0bsd|unlicense|zlib|hpnd|cc0-1\.0|public domain|bsd|bsd-[234]-clause|mpl-2\.0|psf-2\.0|apache-2\.0|apache 2\.0|apache software|apache license 2\.0|python software foundation|mozilla public license 2\.0( \(mpl 2\.0\))?)( license)?'

term_ok() {
  local t="${1#"${1%%[![:space:]]*}"}"; t="${t%"${t##*[![:space:]]}"}"
  [[ "$t" =~ ^($PERMISSIVE_TERM)$ ]]
}

# ok when some OR alternative has every AND term (also " / ") permissive. A parenthesised
# expression loses its precedence here, so it passes only when every term is permissive.
classify() {
  local text alt term; text="$(printf '%s' "$1" | LC_ALL=C tr '[:upper:]\t\n' '[:lower:]  ' | LC_ALL=C tr -s ' ')"
  # Any other control byte could pose as a separator, so it fails closed. Tab and newline were spaces above.
  if [[ "$(printf '%s' "$text" | LC_ALL=C tr -d '[:cntrl:]')" != "$text" ]]; then echo flagged; return; fi
  local paren=0; [[ "$text" == *[\(\)]* ]] && paren=1
  text="${text//[()]/ }"; text="$(printf '%s' "$text" | tr -s ' ')"; text=" ${text} "
  text="${text// and /$'\n'}"; text="${text// \/ /$'\n'}"
  if [[ $paren -eq 1 ]]; then text="${text// or /$'\n'}"; fi
  local alts; alts="${text// or /$'\x01'}"
  while IFS= read -r -d $'\x01' alt || [[ -n "$alt" ]]; do
    local all=1
    while IFS= read -r term; do term_ok "$term" || { all=0; break; }; done <<<"$alt"
    [[ $all -eq 1 ]] && { echo ok; return; }
  done < <(printf '%s' "$alts")
  echo flagged
}

if [[ "${1:-}" == "--classify" ]]; then classify "${2:-}"; exit 0; fi

ROOT="$(git rev-parse --show-toplevel)" || { echo "not inside a git repo" >&2; exit 1; }
cd "$ROOT" || exit 1
SECRET_FAIL=0
FINDINGS=0

secret_scan() {
  local report; report="$(mktemp)"
  gitleaks git --log-opts="--all" --redact=100 --no-banner --no-color \
    --report-format json --report-path "$report" . >/dev/null 2>&1
  local code=$?
  if [[ $code -ne 0 && $code -ne 1 ]]; then
    echo "secret scan: FAIL (gitleaks could not run, exit $code)"; rm -f "$report"; SECRET_FAIL=1; return
  fi
  if [[ $code -eq 0 ]]; then
    echo "secret scan: PASS (0 findings, all refs)"; rm -f "$report"; return
  fi
  local count lines
  if ! count="$(jq 'length' "$report")" || ! lines="$(jq -r '.[] | "  rule=\(.RuleID) file=\(.File) commit=\(.Commit[0:12])"' "$report")"; then
    echo "secret scan: FAIL (gitleaks reported leaks but its report could not be read)"
    rm -f "$report"; SECRET_FAIL=1; return
  fi
  echo "secret scan: FAIL ($count findings, values redacted)"
  printf '%s\n' "$lines"
  SECRET_FAIL=1
  rm -f "$report"
}

brand_scan() {
  local pattern; pattern="$(IFS='|'; echo "${BRANDS[*]}")"
  local excludes=(); local skip
  for skip in "${BRAND_SKIP[@]}"; do excludes+=(":!$skip"); done
  # -o prints file:line:matched-word only, never the line, so no literal on a hit line is echoed.
  # git grep exits 0 on a hit and 1 on none. A file it cannot read gives exit 1 plus a stderr
  # error, so any stderr or an exit above 1 means the scan is incomplete: fail, never PASS.
  local raw code=0 err; err="$(mktemp)"
  raw="$(git grep -n -o -i -I -E "$pattern" -- . "${excludes[@]}" ':!uv.lock' ':!pnpm-lock.yaml' 2>"$err")" || code=$?
  if [[ $code -gt 1 || -s "$err" ]]; then
    echo "brand scan: FAIL (git grep exit $code, could not read every tracked file)"; rm -f "$err"; FINDINGS=1; return
  fi
  rm -f "$err"
  local hits; hits="$(printf '%s\n' "$raw" | awk '!seen[$0]++')"
  echo "brand hits: $(printf '%s' "$hits" | cut -d: -f1,2 | sort -u | grep -c .) lines"
  [[ -n "$hits" ]] && { printf '%s\n' "$hits" | sed 's/^/  /'; FINDINGS=1; }
}

python_licenses() {
  [[ -f pyproject.toml ]] || return 0
  local runner=(python3); command -v uv >/dev/null && runner=(uv run --no-sync python)
  "${runner[@]}" - <<'PY'
import re, tomllib
from importlib import metadata
with open("pyproject.toml", "rb") as f:
    deps = tomllib.load(f).get("project", {}).get("dependencies", [])
for dep in deps:
    name = re.split(r"[\[<>=!~ ;]", dep, maxsplit=1)[0]
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        print(f"{name}\tUNKNOWN"); continue
    text = meta.get("License-Expression") or ""
    if not text:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        legacy = (meta.get("License") or "").strip().splitlines()
        text = " / ".join(classifiers) or (legacy[0][:80] if legacy else "")
    print(f"{name}\t{text or 'UNKNOWN'}")
PY
}

js_licenses() {
  local manifest dir name names license
  for manifest in $(git ls-files '*package.json' | grep -v '^package.json$'); do
    dir="$(dirname "$manifest")"
    names="$(jq -r '((.dependencies // {}) + (.devDependencies // {})) | keys[]' "$manifest")" || return 1
    for name in $names; do
      license="$(jq -r '.license // empty' "$dir/node_modules/$name/package.json" 2>/dev/null)"
      [[ -z "$license" ]] && license="$(npm view "$name" license --fetch-retries=0 --fetch-timeout=15000 2>/dev/null | head -1)"
      echo "$name	${license:-UNKNOWN}"
    done
  done
}

license_scan() {
  local rows py js flagged=0 name license
  if ! py="$(python_licenses)"; then echo "licenses: FAIL (python lister failed)"; FINDINGS=1; fi
  if ! js="$(js_licenses)"; then echo "licenses: FAIL (js lister failed)"; FINDINGS=1; fi
  rows="$(printf '%s\n%s\n' "$py" "$js" | sort -u)"
  echo "licenses:"
  while IFS=$'\t' read -r name license; do
    [[ -z "$name" ]] && continue
    if [[ "$(classify "$license")" == flagged ]]; then echo "  FLAGGED $name: $license"; flagged=$((flagged+1))
    else echo "  ok $name: $license"; fi
  done <<<"$rows"
  echo "licenses flagged: $flagged"
  [[ $flagged -gt 0 ]] && FINDINGS=1
}

secret_scan
brand_scan
license_scan
if [[ $SECRET_FAIL -eq 1 ]]; then echo "result: FAIL (secrets)"; exit 1; fi
if [[ $FINDINGS -eq 1 ]]; then echo "result: FINDINGS (brands or licenses to review)"; exit 2; fi
echo "result: PASS"
