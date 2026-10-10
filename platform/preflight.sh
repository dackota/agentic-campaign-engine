#!/usr/bin/env bash
# Stop `make up` before it creates anything: tools, the .env file, free Docker memory.
# Only the presence of .env is checked; its values are never read.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAIN="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
ENV_FILE="${ENV_FILE:-$MAIN/.env}"
MIN_FREE_GIB="${MIN_FREE_GIB:-6}"
BYTES_PER_GIB=1073741824
KIB_PER_GIB=1048576
MIB_PER_GIB=1024

fail() { echo "preflight: $*" >&2; exit 1; }

for tool in k3d docker kubectl helm jq; do
  command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool is not on PATH"
done

[ -f "$ENV_FILE" ] || fail "missing .env file at $ENV_FILE (copy .env.example and fill it in)"

total_bytes="$(docker info --format '{{.MemTotal}}')"
# Sum the running containers' memory (docker stats prints e.g. "3.54GiB / 23.4GiB").
used_gib="$(docker stats --no-stream --format '{{.MemUsage}}' | awk -v bytes="$BYTES_PER_GIB" -v kib="$KIB_PER_GIB" -v mib="$MIB_PER_GIB" '
  { split($0, p, " / "); v = p[1]; n = v + 0
    # GiB values need no conversion.
    if (v ~ /MiB/) n /= mib; else if (v ~ /[kK]iB/) n /= kib; else if (v !~ /GiB/) n /= bytes
    sum += n }
  END { printf "%.2f", sum }')"
free_gib="$(awk -v t="$total_bytes" -v u="$used_gib" -v bytes="$BYTES_PER_GIB" 'BEGIN { printf "%.1f", t / bytes - u }')"
awk -v f="$free_gib" -v m="$MIN_FREE_GIB" 'BEGIN { exit !(f + 0 < m + 0) }' &&
  fail "free Docker memory is ${free_gib} GiB, below the ${MIN_FREE_GIB} GiB needed (raise Docker's memory or stop containers)"
echo "preflight ok: free Docker memory ${free_gib} GiB"
