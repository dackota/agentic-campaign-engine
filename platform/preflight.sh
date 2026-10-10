#!/usr/bin/env bash
# Stop `make up` before it creates anything: tools, the .env file, free Docker memory.
# Only the presence of .env is checked; its values are never read.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"
MIN_FREE_GIB="${MIN_FREE_GIB:-6}"

fail() { echo "preflight: $*" >&2; exit 1; }

for tool in k3d docker kubectl helm jq; do
  command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool is not on PATH"
done

[ -f "$ENV_FILE" ] || fail "missing .env file at $ENV_FILE (copy .env.example and fill it in)"

total_bytes="$(docker info --format '{{.MemTotal}}')"
# Sum the running containers' memory (docker stats prints e.g. "3.54GiB / 23.4GiB").
used_gib="$(docker stats --no-stream --format '{{.MemUsage}}' | awk '
  { split($0, p, " / "); v = p[1]; n = v + 0
    if (v ~ /GiB/) n *= 1; else if (v ~ /MiB/) n /= 1024; else if (v ~ /[kK]iB/) n /= 1048576; else n /= 1073741824
    sum += n }
  END { printf "%.2f", sum }')"
free_gib="$(awk -v t="$total_bytes" -v u="$used_gib" 'BEGIN { printf "%.1f", t / 1073741824 - u }')"
awk -v f="$free_gib" -v m="$MIN_FREE_GIB" 'BEGIN { exit !(f + 0 < m + 0) }' &&
  fail "free Docker memory is ${free_gib} GiB, below the ${MIN_FREE_GIB} GiB needed (raise Docker's memory or stop containers)"
echo "preflight ok: free Docker memory ${free_gib} GiB"
