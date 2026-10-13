"""`make evals` runs the gate locally; CI waits until the repo is public (#63)."""

import subprocess

from tests.tooling.gateway_files import ROOT


def test_make_evals_runs_the_gate_and_help_lists_it() -> None:
    dry = subprocess.run(
        ["make", "-n", "evals"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    helped = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert "tests.harness.run_evals" in dry
    assert "--baseline evals/baseline.json" in dry
    assert any(line.split()[:1] == ["evals"] for line in helped.splitlines())


def test_no_workflow_runs_the_eval_stack_yet() -> None:
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        assert "make evals" not in workflow.read_text(), workflow.name
        assert "run_evals" not in workflow.read_text(), workflow.name
