"""The demo recording: apps/web/demo/record.mjs, a plain Node script on the Playwright library,
captions every beat of docs/demo-script.md, and the README shows the GIF and links the video.
The frames themselves are checked by hand (ffmpeg, one frame per caption): no test sees a frame."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "docs/demo-script.md").read_text()
RECORDING = (ROOT / "apps/web/demo/record.mjs").read_text()
RECORD_SH = (ROOT / "scripts/record-demo.sh").read_text()
README = (ROOT / "README.md").read_text()
GIF = ROOT / "docs/demo.gif"
GIF_MAX_BYTES = 5 * 1024 * 1024


def test_recording_has_a_caption_for_every_beat_of_the_script() -> None:
    beats = {int(n) for n in re.findall(r"^## Beat (\d+)", SCRIPT, re.M)}
    captioned = {int(n) for n in re.findall(r"""\bbeat\(page, (\d+),""", RECORDING)}

    assert beats == set(range(1, 11))
    assert captioned == beats


def test_recording_is_a_plain_script_not_a_playwright_test() -> None:
    assert "chromium.launch(" in RECORDING and "recordVideo" in RECORDING
    assert not re.search(r"\b(test|expect)\(", RECORDING)
    assert "demo/record.mjs" in RECORD_SH
    assert "playwright test" not in RECORD_SH
    assert not (ROOT / "apps/web/demo/record.spec.ts").exists()
    assert not (ROOT / "apps/web/demo/demo.config.ts").exists()


def test_readme_shows_the_gif_and_links_the_video() -> None:
    assert "![" in README and "(docs/demo.gif)" in README
    assert re.search(r"\[[^\]]*video[^\]]*\]\(docs/demo\.mp4\)", README, re.I)
    assert "Video and demo GIF: TODO" not in README


def test_demo_gif_is_under_5_mb() -> None:
    assert GIF.stat().st_size < GIF_MAX_BYTES
