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

command -v ffmpeg >/dev/null || { echo "ffmpeg is missing: brew install ffmpeg" >&2; exit 1; }

rm -rf "$OUT_DIR"
(cd "$ROOT/apps/web" && pnpm exec playwright test --config demo/demo.config.ts)

webm=$(find "$OUT_DIR" -name '*.webm' | head -n 1)
[ -n "$webm" ] || { echo "no video recorded under $OUT_DIR" >&2; exit 1; }

ffmpeg -y -loglevel error -i "$webm" -c:v libx264 -crf 28 -preset slow -pix_fmt yuv420p \
  -movflags +faststart -an "$ROOT/docs/demo.mp4"

palette=$(mktemp -t demo-palette).png
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
