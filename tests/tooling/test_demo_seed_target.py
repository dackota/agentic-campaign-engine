"""`make seed-demo` runs the demo seed, and `make help` lists it."""

import subprocess
from pathlib import Path

import pytest

from tests.harness import demo_seed
from tests.tooling.gateway_files import ROOT


def test_make_seed_demo_runs_the_seed_command_and_help_lists_it() -> None:
    dry = subprocess.run(
        ["make", "-n", "seed-demo"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    helped = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert "tests.harness.demo_seed" in dry
    assert any(line.split()[:1] == ["seed-demo"] for line in helped.splitlines())


def test_tokens_file_missing_a_demo_user_exits_naming_the_email(tmp_path: Path) -> None:
    tokens = tmp_path / "tokens.json"
    tokens.write_text('{"dg-owner@demo.example": "secret-value"}')

    with pytest.raises(SystemExit) as stopped:
        demo_seed.main(["--api-url", "http://127.0.0.1:1", "--tokens-file", str(tokens)])

    assert "dg-approver@demo.example" in str(stopped.value)
    assert "secret-value" not in str(stopped.value)
