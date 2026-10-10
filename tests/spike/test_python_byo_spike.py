"""S0 spike artifacts for the Python BYO wake-up test (offline checks).

The behaviour itself is proved live by scripts/spike/python-wakeup.sh against the
k3d-ace-spike cluster. These tests hold the recorded evidence to the criteria.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "manifests/spike/python-byo.yaml"
SCRIPT = ROOT / "scripts/spike/python-wakeup.sh"
DECISION = ROOT / "docs/decisions/python-byo-wakeup.md"
LOG = ROOT / "docs/spike-log.md"
BUGS = ROOT / "docs/upstream-bugs"


def test_manifest_is_python_byo_pinned_by_digest() -> None:
    text = MANIFEST.read_text()
    assert "byo: {}" in text
    assert re.search(r"kagent-adk@sha256:[0-9a-f]{64}", text)
    assert "KAGENT_PORT" in text and '"80"' in text
    assert "command:" in text


def test_wakeup_script_suspends_then_resends() -> None:
    text = SCRIPT.read_text()
    assert "SendMessage" in text
    assert "ACTOR_STATE_SUSPENDED" in text
    assert text.count("send_message") >= 3  # definition plus before and after the suspend


def test_result_recorded_in_spike_log() -> None:
    text = LOG.read_text()
    assert re.search(r"^## .*Python BYO", text, re.M)
    assert re.search(r"Result: (survived|crashed)", text)


def test_crash_has_upstream_bug_draft() -> None:
    result = re.search(r"Result: (survived|crashed)", DECISION.read_text())
    assert result, "decision must state the result"
    if result.group(1) == "crashed":
        drafts = [p for p in BUGS.glob("*python*.md")]
        assert drafts, "a crash needs a ready-to-file bug draft"
        assert "Repro" in drafts[0].read_text()


def test_decision_states_go_or_no_go() -> None:
    text = DECISION.read_text()
    assert "S13" in text
    assert re.search(r"Decision: \*\*(go|no-go)\*\*", text)
