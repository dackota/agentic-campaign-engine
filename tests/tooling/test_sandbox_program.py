"""Live design step (fallback in the ADR): the engine runs the program the design agent wrote
in a standalone sandbox and reads the cards from stdout. A fake `kagent` on PATH stands in."""

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from ace_engine import contracts
from ace_engine.contracts import violations
from campaign_worker import sandbox
from temporalio.exceptions import ApplicationError

from tests.harness.fake_kagent import FAKE

PROGRAM = (
    "for n in 1 2; do printf '<svg width=\"1200\"/>' > /tmp/c$n.svg; "
    "echo \"CARD $n $(base64 < /tmp/c$n.svg | tr -d '\\n')\"; done"
)


@pytest.fixture
def kagent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "kagent"
    binary.write_text(FAKE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    return log


def _run(program: str) -> dict[str, Any]:
    config = sandbox.SandboxConfig(kagent_bin=os.environ["FAKE_BIN"], api_url="http://x")
    return asyncio.run(sandbox.run_design_program(program, config))


def test_program_runs_in_the_sandbox_and_cards_come_back(
    kagent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BIN", str(kagent.parent / "kagent"))

    output = _run(PROGRAM)

    assert violations(output, contracts.DESIGN_CARDS_SCHEMA) == []
    assert [c["name"] for c in output["cards"]] == ["social-card-1.svg", "social-card-2.svg"]
    calls = kagent.read_text()
    assert "sandbox create ace-design-sandbox" in calls and "sandbox delete sb-1" in calls
    assert "CARD" not in calls.split("sandbox exec")[1].split("base64 -d")[0]


def test_sandbox_is_deleted_when_the_program_prints_no_cards(
    kagent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BIN", str(kagent.parent / "kagent"))

    with pytest.raises(ApplicationError) as err:
        _run("echo nothing")

    assert err.value.non_retryable
    assert "sandbox delete sb-1" in kagent.read_text()


def test_design_reply_may_carry_a_program_instead_of_cards() -> None:
    assert violations({"program": "echo hi"}, contracts.DESIGN_REPLY_SCHEMA) == []
    assert violations({"cards": []}, contracts.DESIGN_REPLY_SCHEMA)
    assert violations({"program": 3}, contracts.DESIGN_REPLY_SCHEMA)
