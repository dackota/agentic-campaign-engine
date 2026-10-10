"""Shared code is written once: constants, checks, and helpers that two places need."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web/src"


def _python_sources() -> list[Path]:
    return [
        p
        for top in ("apps", "tests", "services")
        for p in (ROOT / top).rglob("*.py")
        if "node_modules" not in p.parts
    ]


def test_report_marker_is_defined_once() -> None:
    definitions = [
        p for p in _python_sources() if re.search(r"^REPORT_MARKER\s*=", p.read_text(), re.M)
    ]
    assert [p.relative_to(ROOT).as_posix() for p in definitions] == [
        "apps/engine/ace_engine/contracts.py"
    ]


def test_campaign_404_is_written_once() -> None:
    text = (ROOT / "apps/api/campaign_api/main.py").read_text()
    assert text.count('"campaign not found"') == 1


def test_web_error_message_helper_is_shared() -> None:
    sources = {p.name: p.read_text() for p in WEB.glob("*.ts*")}
    inline = [name for name, text in sources.items() if "instanceof Error" in text]
    assert inline == ["messages.ts"]
    assert "export function messageOf" in sources["messages.ts"]
    assert sources["App.tsx"].count("messageOf(") == 2
    assert "messageOf(" in sources["useRunEvents.ts"]


def test_web_statuses_come_from_one_const_tuple() -> None:
    text = (WEB / "api.ts").read_text()
    assert re.search(r"STATUSES = \[[^\]]*\] as const", text)
    assert '"drafting" |' not in text
    assert "(typeof STATUSES)[number]" in text


def test_no_test_module_imports_another() -> None:
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "tests").rglob("*.py")
        if re.search(r"^from tests\.\S*\.test_\w+ import", p.read_text(), re.M)
    ]
    assert offenders == []
    helpers = (ROOT / "tests/api/helpers.py").read_text()
    for name in ("def create", "def settle", "def until_status"):
        assert name in helpers
    settle = helpers.split("def settle", 1)[1].split("\ndef ", 1)[0]
    assert "until_status(" in settle
