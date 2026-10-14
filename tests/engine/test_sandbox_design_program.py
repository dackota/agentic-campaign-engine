"""The design agent replies with a program; the engine runs it in the sandbox (a fake `kagent`
runs it for real with sh) and keeps the two cards it printed."""

import asyncio
import base64
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from campaign_worker import sandbox
from campaign_worker.sandbox import SandboxConfig
from sqlalchemy.engine import Engine
from temporalio.exceptions import ApplicationError

from tests.harness.fake_kagent import FAKE
from tests.harness.scripted_agent import DESIGN_PROGRAM, PROGRAM_MARKER
from tests.support.dag import REPORT
from tests.support.scripted_worker import scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

CARD_NAMES = ["social-card-1.svg", "social-card-2.svg"]
SVG = '<svg width="1200" height="630"/>'


@pytest.fixture
def fake_kagent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A fake `kagent` on PATH; the path of the log of the calls it got."""
    binary = tmp_path / "kagent"
    binary.write_text(FAKE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    yield log


def _card_line(n: int, svg: str = SVG) -> str:
    return f"CARD {n} {base64.b64encode(svg.encode()).decode()}"


def test_a_program_is_run_in_a_sandbox_that_is_deleted_and_its_cards_come_back(
    fake_kagent: Path,
) -> None:
    cards = asyncio.run(
        sandbox.run_design_program(
            DESIGN_PROGRAM, SandboxConfig(api_url="http://kagent.invalid", kagent_bin="kagent")
        )
    )

    calls = fake_kagent.read_text()
    assert [c["name"] for c in cards["cards"]] == CARD_NAMES
    assert all(c["svg"] == SVG for c in cards["cards"])
    assert "sandbox create ace-design-sandbox" in calls
    assert "sandbox delete sb-1" in calls


def test_the_design_step_runs_the_agents_program_and_keeps_only_the_cards(
    sqlite_engine: Engine, fake_kagent: Path
) -> None:
    report = f"{PROGRAM_MARKER}\n{REPORT}"
    campaign = str(seed_campaign(sqlite_engine, CampaignSeed(report=report)))
    worker = scripted_worker(sqlite_engine)

    result = asyncio.run(worker.activities.run_agent_step(campaign, report, "design", {}))

    assert [c["name"] for c in result["output"]["cards"]] == CARD_NAMES
    assert "program" not in result["output"]
    assert "sandbox delete sb-1" in fake_kagent.read_text()


@pytest.mark.parametrize(
    ("stdout", "problem"),
    [
        ("", "did not print card 1"),
        (_card_line(1) + "\n", "did not print card 2"),
        (_card_line(1) + "\nCARD 2 !!not-base64!!\n", "did not print card 2"),
        (_card_line(1) + "\n" + _card_line(2, "not an svg"), "break the contract"),
    ],
)
def test_a_program_that_prints_no_valid_card_fails_the_step_without_a_retry(
    stdout: str, problem: str
) -> None:
    with pytest.raises(ApplicationError) as failure:
        sandbox._cards_from(stdout)

    assert problem in str(failure.value)
    assert failure.value.non_retryable
    assert failure.value.type == sandbox.SANDBOX_FAILED
