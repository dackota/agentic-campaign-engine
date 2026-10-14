#!/usr/bin/env bash
# Records the captioned demo on the fast stack (needs Docker and ffmpeg) and writes
#   docs/demo.mp4  the full video, 1280x720
#   docs/demo.gif  a shorter, smaller loop for the README (under 5 MB)
# The beats follow docs/demo-script.md. No model key is used: the scripted agent plays the agents.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR="$ROOT/apps/web/test-results/demo"
GIF_SPEED=2.5   # the GIF plays this many times faster than the video
GIF_WIDTH=800
GIF_FPS=8
GIF_MAX_BYTES=$((5 * 1024 * 1024))
STACK_START_TIMEOUT_S=240

command -v ffmpeg >/dev/null || { echo "ffmpeg is missing: brew install ffmpeg" >&2; exit 1; }

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# A port the OS has free now, for each service.
free_port() { node -e "const s=require('net').createServer().listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})"; }
export ACE_API_PORT=$(free_port) ACE_WEB_PORT=$(free_port) ACE_DEX_PORT=$(free_port) ACE_MARKETO_PORT=$(free_port)
export VITE_OIDC_ISSUER="http://127.0.0.1:$ACE_DEX_PORT/dex"
export ACE_DEMO_VIDEO_DIR="$OUT_DIR"
for p in . apps/engine apps/api apps/worker services/fakes services/render services/mcp; do
  PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$ROOT/$p"
done
export PYTHONPATH
# The stack starts with Acme's past campaigns (as `make seed-demo` leaves them), so the list is not empty.
export ACE_SEED_DEMO=1

stack_pid="" web_pid=""
stop() {
  # SIGTERM lets the stack remove its containers.
  [ -n "$web_pid" ] && kill "$web_pid" 2>/dev/null || true
  [ -n "$stack_pid" ] && kill -TERM "$stack_pid" 2>/dev/null && wait "$stack_pid" 2>/dev/null || true
}
trap stop EXIT

(cd "$ROOT" && exec uv run python -m tests.harness.serve) &
stack_pid=$!
(cd "$ROOT/apps/web" && exec pnpm exec vite --host 127.0.0.1 --port "$ACE_WEB_PORT" --strictPort) >"$OUT_DIR/vite.log" 2>&1 &
web_pid=$!

wait_for() { # url
  for _ in $(seq 1 $((STACK_START_TIMEOUT_S / 2))); do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    kill -0 "$stack_pid" 2>/dev/null || { echo "the stack exited before it was ready" >&2; return 1; }
    sleep 2
  done
  echo "timed out waiting for $1" >&2; return 1
}
wait_for "http://127.0.0.1:$ACE_API_PORT/healthz"
wait_for "http://127.0.0.1:$ACE_WEB_PORT"

(cd "$ROOT/apps/web" && node demo/record.mjs)
stop
trap - EXIT

webm=$(find "$OUT_DIR" -name '*.webm' | head -n 1)
[ -n "$webm" ] || { echo "no video recorded under $OUT_DIR" >&2; exit 1; }

ffmpeg -y -loglevel error -i "$webm" -c:v libx264 -crf 28 -preset slow -pix_fmt yuv420p \
  -movflags +faststart -an "$ROOT/docs/demo.mp4"

palette="$OUT_DIR/palette.png"
filters="setpts=PTS/$GIF_SPEED,fps=$GIF_FPS,scale=$GIF_WIDTH:-1:flags=lanczos"
ffmpeg -y -loglevel error -i "$webm" -vf "$filters,palettegen=max_colors=96" "$palette"
ffmpeg -y -loglevel error -i "$webm" -i "$palette" \
  -lavfi "$filters [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=4" "$ROOT/docs/demo.gif"
rm -f "$palette"

gif_bytes=$(wc -c <"$ROOT/docs/demo.gif" | tr -d ' ')
if [ "$gif_bytes" -ge "$GIF_MAX_BYTES" ]; then
  echo "docs/demo.gif is $gif_bytes bytes, over 5 MB: raise GIF_SPEED or lower GIF_WIDTH" >&2
  exit 1
fi
ls -lh "$ROOT/docs/demo.mp4" "$ROOT/docs/demo.gif"
