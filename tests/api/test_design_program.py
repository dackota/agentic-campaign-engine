"""Seam 1 at live-style design: the design agent replies with a program, the engine runs it in
the sandbox (a fake `kagent` on PATH runs it for real with sh) and saves the two cards it
printed to the asset library."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.api.helpers import AWAITING, bucket_keys, create_on, read_events
from tests.harness.scripted_agent import PROGRAM_MARKER
from tests.harness.stack import Stack
from tests.tooling.test_sandbox_program import FAKE

CARD_NAMES = ("social-card-1.svg", "social-card-2.svg")


@pytest.fixture
def fake_kagent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    binary = tmp_path / "kagent"
    binary.write_text(FAKE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    yield log


def test_a_program_reply_is_run_in_the_sandbox_and_its_cards_saved(
    stack: Stack, api: httpx.Client, fake_kagent: Path
) -> None:
    report = f"{PROGRAM_MARKER}\nVolt Typhoon targets edge routers"
    campaign = create_on(api, "threat-report-to-campaign", report)
    assert read_events(api, campaign["id"])[-1]["status"] == AWAITING

    steps = {s["step"]: s for s in api.get(f"/campaigns/{campaign['id']}/steps").json()}
    calls = fake_kagent.read_text()

    assert [c["name"] for c in steps["design"]["output"]["cards"]] == list(CARD_NAMES)
    assert "program" not in steps["design"]["output"]
    assert "sandbox create ace-design-sandbox" in calls and "sandbox delete sb-1" in calls
    assert sorted(bucket_keys(stack, f"cards/{campaign['id']}/")) == sorted(
        f"cards/{campaign['id']}/{n}" for n in CARD_NAMES
    )
