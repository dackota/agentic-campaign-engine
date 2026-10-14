"""The demo script: 3 to 5 minutes spoken, plain words, one campaign from report to results,
on screens the web app has. The README's Demo section says how to seed and links the video."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "docs/demo-script.md").read_text()
REPORT = (ROOT / "docs/demo-report.txt").read_text()
README = (ROOT / "README.md").read_text()
WEB_SOURCE = "\n".join(p.read_text() for p in (ROOT / "apps/web/src").glob("*.tsx"))
# About 150 spoken words a minute.
MIN_WORDS, MAX_WORDS = 450, 700
BEAT = re.compile(r"^## Beat \d+", re.M)
REAL_BRANDS = (
    "marketo",
    "workfront",
    "crowdstrike",
    "palo alto",
    "microsoft",
    "google",
    "slack",
    "salesforce",
    "adobe",
    "volt typhoon",
)
JARGON = ("kagent", "temporal", "kubernetes", "a2a", "mcp", "dag", "llm", "json", "webhook", "rls")


def _spoken() -> str:
    beats_only = SCRIPT[SCRIPT.index("## Beat 1") :]
    lines = [
        line
        for line in beats_only.splitlines()
        if line.strip() and not line.startswith(("#", "On screen:"))
    ]
    return " ".join(lines)


def test_script_is_three_to_five_minutes_spoken() -> None:
    words = len(re.findall(r"[A-Za-z0-9'-]+", _spoken()))

    assert MIN_WORDS <= words <= MAX_WORDS, words


def test_script_walks_report_to_results_on_screens_that_exist() -> None:
    beats = BEAT.findall(SCRIPT)
    on_screen = re.findall(r"^On screen: (.+)$", SCRIPT, re.M)
    assert len(beats) >= 5
    assert len(on_screen) == len(beats), "every beat names what is on screen"
    names = [n for line in on_screen for n in re.findall(r"`([^`]+)`", line)]
    assert names
    for name in names:
        assert name in WEB_SOURCE, f"the script names `{name}`, which no screen shows"
    lowered = SCRIPT.lower()
    for word in ("report", "approve", "results", "learn"):
        assert word in lowered, word
    assert lowered.index("report") < lowered.index("approve") < lowered.rindex("results")


def test_script_is_plain_words() -> None:
    lowered = _spoken().lower()
    for term in JARGON:
        assert not re.search(rf"\b{term}\b", lowered), term


def test_script_and_report_name_no_real_brand() -> None:
    assert "Acme Security" in SCRIPT
    for text in (SCRIPT.lower(), REPORT.lower()):
        for brand in REAL_BRANDS:
            assert brand not in text, brand
    assert REPORT.strip()


def test_readme_demo_section_names_seed_command_and_video_link() -> None:
    section = re.search(r"^## Demo\n(.*?)(?=^## )", README, re.M | re.S)
    assert section, "no '## Demo' section"
    body = section.group(1)

    assert "make seed-demo" in body
    assert "docs/demo-script.md" in body
    has_link = re.search(r"\[[^\]]*video[^\]]*\]\(https?://\S+\)", body, re.I)
    assert has_link or "Video and demo GIF: TODO" in body


def test_demo_report_fits_the_scripted_email_body_so_the_draft_is_not_cut_off() -> None:
    # The scripted agent copies the first 300 characters of the report into the email body.
    assert len(REPORT.strip()) <= 300
