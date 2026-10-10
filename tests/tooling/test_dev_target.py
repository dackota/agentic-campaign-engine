"""`make dev` runs Tilt on k3d-ace only, against stub tilt and kubectl programs."""

import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "docs/pinned-versions.md"
TILT_VERSION = "v0.37.8"

TILT_STUB = """#!/bin/sh
echo "tilt $*" >> "$STUB_LOG"
echo "KUBECONFIG=$KUBECONFIG" >> "$STUB_LOG"
case "$1" in
  version) echo "${STUB_TILT_VERSION:-v0.37.8}, built 2026-01-01"; exit 0 ;;
esac
[ -n "$STUB_TILT_FAIL" ] && exit 7
exit 0
"""
KUBECTL_STUB = """#!/bin/sh
echo "kubectl $*" >> "$STUB_LOG"
if [ -n "$STUB_KUBECTL_FAIL" ]; then echo "kubectl: no such context" >&2; exit 1; fi
echo "apiVersion: v1"
exit 0
"""


def _run(
    tmp_path: Path, tools: tuple[str, ...] = ("tilt", "kubectl"), **env: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    bodies = {"tilt": TILT_STUB, "kubectl": KUBECTL_STUB}
    for tool in tools:
        path = bin_dir / tool
        path.write_text(bodies[tool])
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    log.write_text("")
    full_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "ACE_BIN_DIR": str(tmp_path / "nobin"),
        **env,
    }
    result = subprocess.run(
        ["make", "-s", "dev"], cwd=ROOT, env=full_env, capture_output=True, text=True
    )
    return result, log.read_text().splitlines()


def test_make_help_lists_dev() -> None:
    out = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert any(line.split()[:1] == ["dev"] for line in out.splitlines())


def test_make_dev_runs_tilt_on_k3d_ace_only(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    kubectl = [c for c in calls if c.startswith("kubectl")]
    assert kubectl and all("--context k3d-ace" in c for c in kubectl)
    assert any(c.startswith("tilt up") for c in calls)
    # Tilt gets a kubeconfig cut down to k3d-ace, not the user's whole one.
    (kubeconfig,) = [c for c in calls if c.startswith("KUBECONFIG=")][-1:]
    assert kubeconfig != "KUBECONFIG=" and str(tmp_path / ".kube") not in kubeconfig
    assert "spike" not in "\n".join(calls)


def test_make_dev_fails_when_tilt_is_missing_or_wrong_version(tmp_path: Path) -> None:
    result, _ = _run(tmp_path / "a", tools=("kubectl",))
    assert result.returncode != 0 and "tilt" in result.stderr
    result, calls = _run(tmp_path / "b", STUB_TILT_VERSION="v0.1.0")
    assert result.returncode != 0 and TILT_VERSION in result.stderr
    assert not any(c.startswith("tilt up") for c in calls)


def test_make_dev_propagates_kubectl_failure(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, STUB_KUBECTL_FAIL="1")
    assert result.returncode != 0
    assert "k3d-ace" in result.stderr
    assert not any(c.startswith("tilt up") for c in calls)


def test_make_dev_propagates_tilt_exit_status(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, STUB_TILT_FAIL="1")
    assert result.returncode != 0


def test_tilt_and_extension_are_pinned() -> None:
    pins = PINS.read_text()
    assert TILT_VERSION in pins
    assert re.search(r"tilt-extensions.*[0-9a-f]{40}", pins)
    script = (ROOT / "platform/dev.sh").read_text()
    assert TILT_VERSION in script
