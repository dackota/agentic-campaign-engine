"""`make seed-demo` runs the demo seed, and `make help` lists it."""

import subprocess

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
