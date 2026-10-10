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
  *apply*"-f "*)
    if [ -n "$STUB_APPLY_FAIL" ]; then
      case "$*" in *"$STUB_APPLY_FAIL"*) echo "apply refused" >&2; exit 1 ;; esac
    fi
    # Keep every applied manifest file, so tests can read what a step sent to the cluster.
    f=""; prev=""
    for a in "$@"; do [ "$prev" = -f ] && f="$a"; prev="$a"; done
    if [ -f "$f" ]; then { echo "---"; cat "$f"; } >> "$STUB_LOG.applied"; fi ;;
esac
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
case "$*" in
  *openid-configuration*)
    if [ -n "$STUB_DEX_FAIL" ]; then echo "curl: (7) connection refused" >&2; exit 7; fi
    printf '{\n  "issuer": "%s"\n}\n' "${STUB_DEX_ISSUER:-http://dex.ace.localhost:15656/dex}"
    exit 0 ;;
esac
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


# --- the Dex step (platform/dex/) ---

DEX_DIR = ROOT / "platform/dex"
STEP = DEX_DIR / "install.sh"
MANIFEST = DEX_DIR / "dex.yaml"
COREDNS = DEX_DIR / "coredns-custom.yaml"
CONFIG = DEX_DIR / "config.yaml"
ISSUER_FILE = ROOT / "platform/oidc-issuer.txt"
ISSUER = "http://dex.ace.localhost:15656/dex"
WEB_ORIGIN = "http://127.0.0.1:15180"
DEX_IMAGE = (
    "ghcr.io/dexidp/dex:v2.46.0"
    "@sha256:933fcd3f523338c847b88ef84a7145fb2fcb7b9917f08418612afeaaa2001777"
)
CURL_IMAGE = (
    "curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6"
)


def _applied(tmp_path: Path) -> list[dict[str, Any]]:
    text = (tmp_path / "calls.log.applied").read_text()
    return [d for d in yaml.safe_load_all(text) if d]


def test_issuer_file_holds_the_issuer() -> None:
    assert ISSUER_FILE.read_text().strip() == ISSUER


def test_rendered_config_equals_checked_in_config_except_three_fields() -> None:
    result = subprocess.run([STEP, "render"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(result.stdout)
    expected = yaml.safe_load(CONFIG.read_text())
    expected["issuer"] = ISSUER
    expected["web"]["allowedOrigins"] = [WEB_ORIGIN]
    for client in expected["staticClients"]:
        client["redirectURIs"] = [f"{WEB_ORIGIN}/"]
    assert rendered == expected
    original = yaml.safe_load(CONFIG.read_text())
    assert rendered["staticPasswords"] == original["staticPasswords"]
    assert rendered["web"]["http"] == original["web"]["http"]


def test_dex_manifest_pins_image_in_namespace_dex() -> None:
    docs = [d for d in yaml.safe_load_all(MANIFEST.read_text()) if d]
    assert {d["kind"] for d in docs} == {"Namespace", "Deployment", "Service"}
    assert next(d for d in docs if d["kind"] == "Namespace")["metadata"]["name"] == "dex"
    for doc in docs:
        if doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == "dex"
    deploy = next(d for d in docs if d["kind"] == "Deployment")
    images = [c["image"] for c in deploy["spec"]["template"]["spec"]["containers"]]
    assert images == [DEX_IMAGE]


def test_dex_service_is_nodeport_15656_to_5556_mapped_by_cluster_config() -> None:
    docs = [d for d in yaml.safe_load_all(MANIFEST.read_text()) if d]
    service = next(d for d in docs if d["kind"] == "Service")
    assert service["metadata"]["name"] == "dex"
    assert service["spec"]["type"] == "NodePort"
    (port,) = service["spec"]["ports"]
    assert port["port"] == 15656 and port["targetPort"] == 5556
    cluster = yaml.safe_load((ROOT / "platform/ace-cluster.yaml").read_text())
    mapped = {m["port"] for m in cluster["ports"]}
    assert f"15656:{port['nodePort']}" in mapped
    config = yaml.safe_load(CONFIG.read_text())
    assert config["web"]["http"].endswith(f":{port['targetPort']}")


def test_coredns_override_rewrites_issuer_host_to_service_fqdn() -> None:
    cm = yaml.safe_load(COREDNS.read_text())
    assert cm["kind"] == "ConfigMap"
    assert cm["metadata"] == {"name": "coredns-custom", "namespace": "kube-system"}
    ((key, body),) = cm["data"].items()
    assert key.endswith(".override")
    assert body.split() == ["rewrite", "name", "dex.ace.localhost", "dex.dex.svc.cluster.local"]


def test_issuer_is_one_constant_read_by_step_status_and_tiltfile() -> None:
    host = "dex.ace.localhost"
    for path in (
        STEP,
        ROOT / "platform/status.sh",
        ROOT / "Tiltfile",
        ROOT / "platform/install.sh",
    ):
        code = _code(path)
        assert host not in code and "15656" not in code, path
        assert "oidc-issuer.txt" in code or path.name == "install.sh", path
    tilt = _code(ROOT / "Tiltfile")
    assert re.search(r"read_file\(\s*['\"]platform/oidc-issuer\.txt['\"]", tilt)
    assert re.search(r"build_args\s*=\s*\{\s*['\"]VITE_OIDC_ISSUER['\"]\s*:\s*OIDC_ISSUER", tilt)


def test_dex_step_names_only_k3d_ace() -> None:
    code = _code(STEP)
    assert set(re.findall(r"k3d-[\w-]+", code)) == {"k3d-ace"}
    assert "ace-spike" not in code
    for line in code.splitlines():
        if re.search(r"\bkubectl\b", line) and not line.lstrip().startswith("#"):
            assert '--context "$CTX"' in line, line


def test_no_chart_file_names_dex() -> None:
    for path in (ROOT / "charts").rglob("*"):
        if path.is_file():
            text = path.read_text().lower()
            assert "dexidp" not in text and "ghcr.io/dexidp/dex" not in text, path
            assert "coredns-custom" not in text, path


def test_readme_describes_dex_step() -> None:
    text = (ROOT / "platform/README.md").read_text()
    assert "dex/install.sh" in text and "coredns-custom" in text and "oidc-issuer.txt" in text


def test_pinned_versions_lists_check_image() -> None:
    assert CURL_IMAGE.split("@")[0] in (ROOT / "docs/pinned-versions.md").read_text()
    assert CURL_IMAGE.split("@")[1] in (ROOT / "docs/pinned-versions.md").read_text()


def test_up_runs_dex_step_after_gateway_with_ace_context(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    gateway = next(i for i, c in enumerate(calls) if "gateway-install.sh" in c)
    dex_apply = next(i for i, c in enumerate(calls) if "apply" in c and "-f " in c and "dex" in c)
    mock = next(i for i, c in enumerate(calls) if "apply" in c and "mock-llm.yaml" in c)
    assert gateway < dex_apply < mock
    assert all(f"--context {CTX}" in c for c in calls if c.startswith("kubectl"))


def test_up_applies_rendered_config_as_configmap(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    docs = _applied(tmp_path)
    cm = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["namespace"] == "dex")
    config = yaml.safe_load(cm["data"]["config.yaml"])
    assert config["issuer"] == ISSUER
    assert config["web"]["allowedOrigins"] == [WEB_ORIGIN]
    assert config["staticClients"][0]["redirectURIs"] == [f"{WEB_ORIGIN}/"]
    deploy = next(
        d for d in docs if d["kind"] == "Deployment" and d["metadata"].get("namespace") == "dex"
    )
    digest = deploy["spec"]["template"]["metadata"]["annotations"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in digest.values())


def test_up_restarts_coredns_and_waits_after_applying_override(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    docs = _applied(tmp_path)
    assert any(d["metadata"].get("name") == "coredns-custom" for d in docs)
    override = next(
        i for i, c in enumerate(calls) if "coredns-custom" in c or "coredns-custom.yaml" in c
    )
    restart = next(i for i, c in enumerate(calls) if "rollout restart" in c)
    status = next(
        i for i, c in enumerate(calls) if "rollout status" in c and "deployment/coredns" in c
    )
    assert override < restart < status
    assert f"--context {CTX} -n kube-system rollout restart deployment/coredns" in calls[restart]
    assert "--timeout" in calls[status]


def test_dex_rollout_is_awaited_with_a_timeout(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, "up")
    waits = [c for c in calls if "rollout status" in c and "deployment/dex" in c]
    assert waits and all("--timeout" in c and "-n dex" in c for c in waits)


def test_rollout_failure_stops_up(tmp_path: Path) -> None:
    for stuck in ("deployment/coredns", "deployment/dex"):
        result, calls = _run(tmp_path, "up", STUB_ROLLOUT_FAIL=stuck)
        assert result.returncode != 0, stuck
        assert not [c for c in calls if "a2a-smoke.sh" in c], stuck


def test_apply_failure_stops_up(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_APPLY_FAIL="dex")
    assert result.returncode != 0
    assert not [c for c in calls if "rollout restart" in c or "a2a-smoke.sh" in c]


def test_second_up_exits_zero(tmp_path: Path) -> None:
    first, _ = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1")
    second, _ = _run(tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1")
    assert first.returncode == 0 and second.returncode == 0, second.stderr


def test_status_reports_dex(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1")
    assert result.returncode == 0, result.stderr
    assert any(
        line.startswith("ok") and "dex" in line.lower() for line in result.stdout.splitlines()
    )
    assert any(c.startswith("curl") and ISSUER in c for c in calls)


def test_status_fails_when_dex_discovery_unreachable(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_DEX_FAIL="1")
    assert result.returncode != 0
    assert any(
        line.startswith("FAIL") and "dex" in line.lower() for line in result.stdout.splitlines()
    )


def test_status_fails_when_discovery_issuer_differs(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        "status",
        STUB_CLUSTER="1",
        STUB_INSTALLED="1",
        STUB_DEX_ISSUER="http://127.0.0.1:5556/dex",
    )
    assert result.returncode != 0
    assert any(
        line.startswith("FAIL") and "dex" in line.lower() for line in result.stdout.splitlines()
    )
