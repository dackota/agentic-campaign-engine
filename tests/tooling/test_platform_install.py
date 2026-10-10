"""`make up` and `make status` install and report the platform, checked offline.

The real Makefile targets run against stub k3d, docker, kubectl, helm, and curl programs
and stub copies of the spike scripts, so no cluster is touched. The live proof is the
Makefile run on a Mac with Docker.
"""

import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tests.tooling.platform_stubs import DOCKER_STUB, K3D_STUB

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "platform/install.sh"
STATUS = ROOT / "platform/status.sh"
TWIN = ROOT / "platform/mock-agent.yaml"
PINNED = ROOT / "docs/pinned-versions.md"
CTX = "k3d-ace"
RELEASES = (
    "substrate-crds",
    "substrate",
    "kagent-crds",
    "kagent",
    "agentgateway-crds",
    "agentgateway",
)
KEY = "sk-secret-value-never-shown"
OS_ARCHES = ("darwin-amd64", "darwin-arm64", "linux-amd64", "linux-arm64")

KUBECTL_STUB = """#!/bin/sh
echo "kubectl $*" >> "$STUB_LOG"
case "$*" in
  *"get secret"*"-o name"*)
    if [ -n "$STUB_SECRET_FAIL" ]; then echo "kubectl: forbidden" >&2; exit 1; fi
    if [ -n "$STUB_INSTALLED" ]; then
      for s in service-dns-ca-pool pod-identity-ca-pool actor-id-jwt-pool \\
        actor-id-ca-pool egress-mitm-ca-pool; do
        [ "$s" = "$STUB_MISSING_SECRET" ] || echo "secret/$s"
      done
    fi ;;
  *"rollout status"*)
    if [ -n "$STUB_ROLLOUT_FAIL" ]; then
      case "$*" in *"$STUB_ROLLOUT_FAIL"*) echo "rollout stuck" >&2; exit 1 ;; esac
    fi ;;
  *"get agent"*) echo "${STUB_AGENT_READY:-True}" ;;
  *"wait"*) [ -n "$STUB_WAIT_FAIL" ] && { echo "timed out" >&2; exit 1; } ;;
  *Ready*) echo True ;;
  *kubeletVersion*) echo "v1.37.1+k3s1" ;;
esac
exit 0
"""
HELM_STUB = """#!/bin/sh
echo "helm $*" >> "$STUB_LOG"
if [ "$3" = list ]; then
  if [ -n "$STUB_HELM_FAIL" ]; then echo "helm: cluster unreachable" >&2; exit 1; fi
  if [ -n "$STUB_INSTALLED" ]; then
    for r in substrate-crds substrate kagent-crds kagent agentgateway-crds agentgateway; do
      [ "$r" = "$STUB_MISSING_RELEASE" ] || echo "$r"
    done
  fi
fi
exit 0
"""
CURL_STUB = """#!/bin/sh
echo "curl $*" >> "$STUB_LOG"
out=""
while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done
echo "not the real binary" > "$out"
exit 0
"""
ATE_STUB = "#!/bin/sh\nexit 0\n"
SPIKE_STUB = """#!/bin/sh
echo "SPIKE $(basename "$0") KCTX=$KCTX AGENT=$AGENT HARNESS=$HARNESS \\
WORKER_IMAGE=${WORKER_IMAGE:+set}" >> "$STUB_LOG"
[ "$(basename "$0")" = "$STUB_SPIKE_FAIL" ] && { echo "$0 failed" >&2; exit 1; }
if [ "$(basename "$0")" = a2a-smoke.sh ]; then
  n="$(cat "$STUB_LOG.smoke" 2>/dev/null || echo 0)"
  echo $((n + 1)) > "$STUB_LOG.smoke"
  if [ "$n" -lt "${STUB_SMOKE_BUSY:-0}" ]; then
    echo 'FAIL: no answer in response: {"error":{"code":-32004,"message":"not accepted"}}' >&2
    exit 1
  fi
  [ -z "$STUB_SMOKE_OTHER_FAIL" ] || { echo "FAIL: A2A request failed" >&2; exit 1; }
  echo 42
fi
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(
    tmp_path: Path,
    *args: str,
    env_text: str | None = f"OPENCODE_KEY={KEY}\n",
    ate: bool = True,
    **stub_env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    ate_dir = tmp_path / "ate-bin"
    spike = tmp_path / "spike"
    for d in (bin_dir, ate_dir, spike):
        d.mkdir(exist_ok=True)
    bodies = {"docker": DOCKER_STUB, "k3d": K3D_STUB, "kubectl": KUBECTL_STUB, "helm": HELM_STUB}
    for tool in ("k3d", "docker", "kubectl", "helm", "jq", "curl"):
        _exe(
            bin_dir / tool, bodies.get(tool, CURL_STUB if tool == "curl" else "#!/bin/sh\nexit 0\n")
        )
    if ate:
        _exe(ate_dir / "kubectl-ate", ATE_STUB)
    for name in ("install.sh", "gateway-install.sh", "a2a-smoke.sh"):
        _exe(spike / name, SPIKE_STUB)
    dotenv = tmp_path / "dotenv"
    if env_text is not None:
        dotenv.write_text(env_text)
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "ENV_FILE": str(dotenv),
        "ATE_BIN_DIR": str(ate_dir),
        "SPIKE_DIR": str(spike),
        **stub_env,
    }
    result = subprocess.run(
        ["make", "-s", *args], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result, log.read_text().splitlines()


def _spike_calls(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("SPIKE ")]


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_up_calls_spike_scripts_with_ace_context(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    spike = _spike_calls(calls)
    assert [c.split()[1] for c in spike] == ["install.sh", "gateway-install.sh", "a2a-smoke.sh"]
    assert all(f"KCTX={CTX}" in c for c in spike)
    assert "WORKER_IMAGE=set" in spike[0]
    assert "42" in result.stdout
    assert "total time" in result.stdout.lower()


def test_up_applies_mock_then_twin_waits_and_smokes_twin(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    mock = next(i for i, c in enumerate(calls) if "apply" in c and "mock-llm.yaml" in c)
    twin = next(i for i, c in enumerate(calls) if "apply" in c and "mock-agent.yaml" in c)
    wait = next(i for i, c in enumerate(calls) if " wait " in c)
    smoke = next(i for i, c in enumerate(calls) if "a2a-smoke.sh" in c)
    gateway = next(i for i, c in enumerate(calls) if "gateway-install.sh" in c)
    assert gateway < mock < twin < wait < smoke
    assert "--timeout" in calls[wait] and f"--context {CTX}" in calls[wait]
    assert "agent/spike-agent" in calls[wait] and "agent/spike-agent-mock" in calls[wait]
    assert "AGENT=spike-agent-mock" in calls[smoke] and "HARNESS=spike-harness" in calls[smoke]


def test_twin_agent_manifest_is_mock_backed() -> None:
    docs: list[dict[str, Any]] = list(yaml.safe_load_all(TWIN.read_text()))
    template = next(d for d in docs if d["kind"] == "AgentTemplate")
    agent = next(d for d in docs if d["kind"] == "Agent")
    assert template["spec"]["modelConfig"]["name"] == "mock-model"
    assert agent["metadata"]["name"] == "spike-agent-mock"
    assert agent["spec"]["templateRef"]["name"] == template["metadata"]["name"]
    assert agent["spec"]["harnessRef"]["name"] == "spike-harness"
    assert template["metadata"]["name"] != "spike-template"


def test_wait_failure_stops_up_before_the_smoke(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_WAIT_FAIL="1")
    assert result.returncode != 0
    assert not [c for c in calls if "a2a-smoke.sh" in c]


def test_spike_script_failure_stops_up(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_SPIKE_FAIL="gateway-install.sh")
    assert result.returncode != 0
    assert not [c for c in calls if "a2a-smoke.sh" in c]


def test_missing_or_empty_opencode_key_stops_up_before_creating_anything(tmp_path: Path) -> None:
    empties = ("OPENCODE_KEY=\n", 'OPENCODE_KEY=""\n', "OPENCODE_KEY=''\n", "OPENCODE_KEY=   \n")
    for text in ("ANTHROPIC_API_KEY=sk-other-value\n", *empties):
        result, calls = _run(tmp_path, "up", env_text=text)
        out = result.stdout + result.stderr
        assert result.returncode != 0
        assert "OPENCODE_KEY" in out
        assert "sk-other-value" not in out
        assert not [c for c in calls if "cluster create" in c or c.startswith("SPIKE")]


def test_opencode_key_value_never_reaches_output_or_argv(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert KEY not in result.stdout + result.stderr
    assert not [c for c in calls if KEY in c]


def test_rerun_skips_install_but_runs_gateway_install(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1")
    assert result.returncode == 0, result.stderr
    names = [c.split()[1] for c in _spike_calls(calls)]
    assert names == ["gateway-install.sh", "a2a-smoke.sh"]
    assert "skip" in result.stdout.lower() and "substrate" in result.stdout.lower()


def test_missing_ca_pool_secret_runs_install(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_MISSING_SECRET="actor-id-ca-pool"
    )
    assert result.returncode == 0, result.stderr
    assert _spike_calls(calls)[0].split()[1] == "install.sh"


def test_missing_release_runs_install(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_MISSING_RELEASE="kagent"
    )
    assert result.returncode == 0, result.stderr
    assert _spike_calls(calls)[0].split()[1] == "install.sh"


def test_secret_checks_use_names_only(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1")
    secret_gets = [c for c in calls if "get secret" in c]
    assert secret_gets and all("-o name" in c for c in secret_gets)


def test_no_secret_data_commands() -> None:
    for script in (INSTALL, STATUS):
        code = _code(script)
        assert not re.search(r"get secret[^\n]*(-o\s*(yaml|json)|describe)", code), script
        assert not re.search(r"describe\s+secret", code), script
        assert not re.search(r"\b(cat|source|sed|head)\b[^\n]*ENV_FILE", code), script
        assert not re.search(r"^\s*\.\s+.*ENV_FILE", code, re.M), script
        assert "printenv" not in code and not re.search(r"^\s*env\s*$", code, re.M)


def test_every_spike_call_carries_kctx() -> None:
    for script in (INSTALL, STATUS):
        for line in _code(script).splitlines():
            if "scripts/spike" in line or "$SPIKE_DIR" in line:
                if "SPIKE_DIR=" in line and "KCTX" not in line:
                    continue  # the default-path assignment, not a call
                assert 'KCTX="$CTX"' in line or "KCTX=k3d-ace" in line, line
    makefile = (ROOT / "Makefile").read_text()
    for target in ("up", "down", "status", "dev"):
        for match in re.finditer(rf"^{target}[a-z-]*:.*\n((?:\t.*\n?)*)", makefile, re.M):
            for line in match.group(1).splitlines():
                if "scripts/spike" in line:
                    assert "KCTX=k3d-ace" in line, line


def test_kubectl_ate_is_checked_against_pinned_sha(tmp_path: Path) -> None:
    code = _code(INSTALL)
    assert "v0.4.0-alpha1" in code and "codesign --force -s -" in code
    for arch in OS_ARCHES:
        assert re.search(
            rf"{arch}\)?[^\n]*[0-9a-f]{{64}}|{arch}[^\n]*\n[^\n]*[0-9a-f]{{64}}", code
        ), arch


def test_checksum_mismatch_stops_up_and_leaves_no_binary(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", ate=False)
    assert result.returncode != 0
    assert "checksum" in (result.stdout + result.stderr).lower()
    assert not (tmp_path / "ate-bin/kubectl-ate").exists()
    assert not [c for c in calls if c.startswith("SPIKE")]
    assert any(c.startswith("curl") and "v0.4.0-alpha1" in c for c in calls)


def test_existing_binary_is_not_fetched_again(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, "up")
    assert not [c for c in calls if c.startswith("curl")]


def test_pinned_checksums_are_documented() -> None:
    doc = PINNED.read_text()
    shas = re.findall(r'echo "([0-9a-f]{64})"', _code(INSTALL))
    assert len(set(shas)) == len(OS_ARCHES)
    for sha in shas:
        assert sha in doc
    for arch in OS_ARCHES:
        assert arch in doc


def test_gitignore_ignores_local_bin() -> None:
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert ".bin/" in lines
    assert ".bin" in _code(INSTALL)


def test_status_reports_each_platform_part(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert all(line.startswith("ok") for line in lines), lines
    for name in (*RELEASES, "spike-agent", "spike-agent-mock", "agentgateway-proxy"):
        assert any(name in line for line in lines), name
    for dep in ("ate-controller", "kagent-controller"):
        assert any(dep in line for line in lines), dep
    assert all(f"--context {CTX}" in c for c in calls if c.startswith("kubectl"))
    assert all("--kube-context k3d-ace" in c for c in calls if c.startswith("helm"))


def test_status_fails_on_missing_release(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_MISSING_RELEASE="kagent"
    )
    assert result.returncode != 0
    assert any(
        line.startswith("FAIL") and re.search(r"release kagent\b", line)
        for line in result.stdout.splitlines()
    )


def test_status_fails_on_stuck_rollout_and_unready_agent(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        "status",
        STUB_CLUSTER="1",
        STUB_INSTALLED="1",
        STUB_ROLLOUT_FAIL="agentgateway-proxy",
    )
    assert result.returncode != 0
    assert any(
        "FAIL" in line and "agentgateway-proxy" in line for line in result.stdout.splitlines()
    )
    result, _ = _run(
        tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_AGENT_READY="False"
    )
    assert result.returncode != 0
    assert any("FAIL" in line and "spike-agent" in line for line in result.stdout.splitlines())


def test_listing_failure_does_not_read_as_not_installed(tmp_path: Path) -> None:
    helm = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_HELM_FAIL="1")
    secret = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_SECRET_FAIL="1")
    for result, calls in (helm, secret):
        assert result.returncode != 0
        assert not [c for c in calls if c.startswith("SPIKE")]


def test_smoke_retries_while_the_session_is_not_accepted(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_SMOKE_BUSY="1", SMOKE_RETRY_DELAY="0")
    assert result.returncode == 0, result.stderr
    assert len([c for c in calls if "a2a-smoke.sh" in c]) == 2
    assert "42" in result.stdout


def test_smoke_gives_up_after_its_timeout_with_a_clear_message(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path, "up", STUB_SMOKE_BUSY="1000", SMOKE_RETRY_DELAY="1", SMOKE_TIMEOUT="2"
    )
    assert result.returncode != 0
    assert "32004" in result.stdout + result.stderr
    assert "not accepted" in (result.stdout + result.stderr).lower()


def test_smoke_does_not_retry_other_failures(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_SMOKE_OTHER_FAIL="1", SMOKE_RETRY_DELAY="0")
    assert result.returncode != 0
    assert len([c for c in calls if "a2a-smoke.sh" in c]) == 1
