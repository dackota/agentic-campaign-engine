#!/usr/bin/env bash
# S7 live proof: the design agent's code runs in a standalone kagent sandbox and makes two
# social cards; a host the sandbox does not need is not reachable from inside it; the
# sandbox is deleted after. Prints the two cards' sizes and exits 0 only when all hold.
# Needs kubectl/kagent/jq; ACE_BIN defaults to .scratch/bin of the main checkout (untracked).
# Never the spike cluster: KCTX defaults to k3d-ace. Reads no .env and prints no env.
set -euo pipefail

COMMON="$(git rev-parse --git-common-dir)"
export PATH="${ACE_BIN:-$(cd "$COMMON/.." && pwd)/.scratch/bin}:$PATH"
KCTX="${KCTX:-k3d-ace}"
NS="${NS:-kagent}"
TEMPLATE="${TEMPLATE:-ace-design-sandbox}"
LOCAL_PORT="${LOCAL_PORT:-18123}"
PROBE_HOST="${PROBE_HOST:-example.com}"
REQUEST_ID="s7-$(date +%s)-$RANDOM"
CODE_FILE="${CODE_FILE:-}"

fail() { echo "FAIL: $*" >&2; exit 1; }
for tool in kubectl kagent jq base64; do command -v "$tool" >/dev/null || fail "$tool not on PATH"; done

kubectl --context "$KCTX" port-forward -n "$NS" svc/kagent-controller "$LOCAL_PORT:8083" >/dev/null 2>&1 &
PF=$!
ID=""
ks() { kagent --api-url "http://localhost:$LOCAL_PORT" --gateway-url "http://localhost:$LOCAL_PORT" -n "$NS" "$@"; }
cleanup() {
  if [ -n "$ID" ]; then
    # shellcheck disable=SC2310  # wrapper: ks is one kagent call, so its status is kagent's
    ks sandbox delete "$ID" >/dev/null 2>&1 || echo "WARN: sandbox $ID not deleted" >&2
  fi
  kill $PF 2>/dev/null || true
}
trap cleanup EXIT
for _ in $(seq 1 30); do
  curl -fs "http://localhost:$LOCAL_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

# The code the design agent writes. A program of its own can be passed in CODE_FILE; the
# default draws the two cards with the shell alone, since the sandbox has no package source.
read -r -d '' DEFAULT_CODE <<'CODE' || true
for n in 1 2; do
  printf '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"><rect width="1200" height="630" fill="#0b5fff"/><text x="80" y="330" fill="#fff" font-size="56">Card %s</text></svg>\n' "$n" > "/tmp/social-card-$n.svg"
done
for n in 1 2; do echo "CARD $n $(cat /tmp/social-card-$n.svg | base64 | tr -d '\n')"; done
CODE
if [ -n "$CODE_FILE" ]; then CODE="$(cat "$CODE_FILE")"; else CODE="$DEFAULT_CODE"; fi

# shellcheck disable=SC2310  # wrapper: ks is one kagent call, so its status is kagent's
created="$(ks sandbox create "$TEMPLATE" --request-id "$REQUEST_ID" --name "$REQUEST_ID" -o json)" \
  || fail "sandbox create failed"
ID="$(echo "$created" | jq -r .id)"
state="$(echo "$created" | jq -r .state)"
echo "created: $ID $state"
[ "$state" = "RUNTIME_STATE_READY" ] || fail "sandbox not ready: $created"

encoded="$(printf '%s' "$CODE" | base64 | tr -d '\n')"
# shellcheck disable=SC2310  # wrapper: ks is one kagent call, so its status is kagent's
out="$(ks sandbox exec "$ID" -- sh -c "echo $encoded | base64 -d > /tmp/make-cards.sh && sh /tmp/make-cards.sh")" \
  || fail "the code failed in the sandbox"
cards=0
for n in 1 2; do
  line="$(echo "$out" | grep "^CARD $n " || true)"
  svg="$(echo "$line" | cut -d' ' -f3 | base64 -d 2>/dev/null || true)"
  [[ "$svg" == "<svg"* ]] || fail "card $n did not come back as an SVG"
  echo "card $n: ${#svg} bytes"
  cards=$((cards + 1))
done
[ "$cards" -eq 2 ] || fail "expected 2 cards"

# A host the sandbox does not need must not answer (egress is deny-by-default).
# shellcheck disable=SC2310  # wrapper: ks is one kagent call, so its status is kagent's
probe="$(ks sandbox exec "$ID" -- sh -c "wget -T5 -qO- http://$PROBE_HOST 2>&1; echo exit=\$?" || true)"
if echo "$probe" | grep -q "exit=0"; then
  fail "$PROBE_HOST is reachable from the sandbox"
fi
echo "$PROBE_HOST: NOT REACHABLE from the sandbox ($(echo "$probe" | head -1))"

# shellcheck disable=SC2310  # wrapper: ks is one kagent call, so its status is kagent's
ks sandbox delete "$ID" >/dev/null || fail "delete failed"
final="$(ks sandbox get "$ID" -o json | jq -r .state)"
echo "after delete: $final"
[ "$final" = "RUNTIME_STATE_DELETED" ] || fail "sandbox not deleted: $final"
ID=""
echo "DELETED"
