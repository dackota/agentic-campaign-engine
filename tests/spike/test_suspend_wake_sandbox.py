"""S0 spike at live depth: suspend/wake and standalone sandboxes on the k3d cluster.

The seam is the scripts in scripts/spike/, driven against kube context k3d-ace-spike.
They skip when that cluster is not reachable. The findings are checked in the spike log.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KCTX = "k3d-ace-spike"
SPIKE_LOG = ROOT / "docs" / "spike-log.md"


def _cluster_up() -> bool:
    try:
        done = subprocess.run(
            ["kubectl", "--context", KCTX, "get", "agent", "spike-agent", "-n", "kagent"],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


live = pytest.mark.skipif(not _cluster_up(), reason=f"cluster {KCTX} not reachable")


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "spike" / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _section(title_word: str) -> str:
    text = SPIKE_LOG.read_text()
    match = re.search(rf"^## [^\n]*{title_word}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"spike log has no section about {title_word}"
    return match.group(1)


@live
def test_idle_session_suspends_and_wake_keeps_context() -> None:
    done = _run("suspend-wake.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ACTOR_STATE_SUSPENDED" in done.stdout
    assert "violet-otter-17" in done.stdout.split("REPLY:")[-1]


@live
def test_standalone_sandbox_runs_command_and_is_deleted() -> None:
    done = _run("sandbox.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "hello from s21 sandbox" in done.stdout
    assert "DELETED" in done.stdout


def test_spike_log_records_sandbox_network_limits() -> None:
    body = _section("Sandbox network")
    assert re.search(r"egress|outbound", body, re.I)
    assert re.search(r"ingress|inbound", body, re.I)


def test_spike_log_records_platform_ram() -> None:
    body = _section("Platform RAM")
    assert re.search(r"\d+(\.\d+)?\s*(MiB|GiB)", body)
    assert "suspended" in body.lower()
