"""S1 failover and team token limits at live depth on the k3d cluster.

Runs scripts/spike/gateway-failover-check.sh against kube context k3d-ace-spike. It
skips when that cluster is not reachable.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KCTX = "k3d-ace-spike"
CLUSTER_PROBE_TIMEOUT_S = 20
SCRIPT_TIMEOUT_S = 300


def _gateway_up() -> bool:
    try:
        done = subprocess.run(
            [
                "kubectl",
                "--context",
                KCTX,
                "get",
                "deploy/agentgateway-proxy",
                "-n",
                "agentgateway-system",
            ],
            capture_output=True,
            timeout=CLUSTER_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


@pytest.mark.skipif(not _gateway_up(), reason=f"gateway on {KCTX} not reachable")
def test_failover_check_passes() -> None:
    done = subprocess.run(
        ["bash", str(ROOT / "scripts/spike/gateway-failover-check.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_S,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "ok failover" in out
    assert "ok team-a 429" in out and "ok team-b 200" in out
    assert "ok tokens per team" in out
    assert out.rstrip().endswith("PASS")
