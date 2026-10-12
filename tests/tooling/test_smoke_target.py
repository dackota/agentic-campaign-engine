"""`make smoke` is the platform smoke test: `make up`, then one scripted campaign at live depth."""

import subprocess

from tests.tooling.gateway_files import ROOT

SMOKE = ROOT / "platform/smoke.sh"
HAPPY_PATH = (
    "tests/api/test_campaign_approval.py"
    "::test_run_waits_for_approval_after_draft_and_api_can_approve"
)


def _code() -> list[str]:
    return [
        line.strip()
        for line in SMOKE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_make_smoke_runs_the_smoke_script_and_help_lists_it() -> None:
    dry = subprocess.run(
        ["make", "-n", "smoke"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    helped = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert "platform/smoke.sh" in dry
    assert any(line.split()[:1] == ["smoke"] for line in helped.splitlines())


def test_smoke_script_brings_the_platform_up_then_runs_the_happy_path_at_live_depth() -> None:
    lines = _code()
    up = next(i for i, line in enumerate(lines) if line.startswith("make up"))
    run = next(i for i, line in enumerate(lines) if HAPPY_PATH in line)

    assert up < run
    assert "ACE_DEPTH=live" in lines[run]
    assert "pytest" in lines[run]
