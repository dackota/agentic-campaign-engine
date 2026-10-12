"""S1 failover and team token limits at live depth on the k3d cluster.

Runs scripts/spike/gateway-failover-check.sh against kube context k3d-ace-spike. It
skips when that cluster is not reachable.
"""

import os
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
# The script needs OpenCode (group 1) healthy when it starts, so the first call fails over
# and logs retry.attempt=1 (docs/spike-log.md, broken key test). When an earlier run's
# eviction of group 1 outlives the backend's recreate and the 5 s settle, group 2 answers on
# the first attempt: 200 from mock-llm, no retry.attempt, and the check fails though failover
# worked. So it runs only on request, and a run that asks for it still fails on a regression.
@pytest.mark.skipif(
    os.environ.get("ACE_SPIKE_FAILOVER") != "1",
    reason="group 1 can stay evicted from an earlier run; set ACE_SPIKE_FAILOVER=1 to run it",
)
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
