"""`make up`, `make down`, `make status` for the `ace` cluster, checked offline.

The real Makefile targets run against stub k3d, docker, and kubectl programs, so no
cluster is touched. The live proof is the Makefile run on a Mac with Docker.
"""

import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC_CONFIG = ROOT / "k3d/ace-spike.yaml"
CONFIG = ROOT / "platform/ace-cluster.yaml"
CLUSTER_SCRIPT = ROOT / "platform/cluster.sh"
PLAYWRIGHT = ROOT / "apps/web/playwright.config.ts"
TOOLS = ("k3d", "docker", "kubectl", "helm", "jq")

DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
case "$1 $2" in
  "info --format") echo "${STUB_MEM_TOTAL:-25159827456}" ;;
  "stats --no-stream") echo "${STUB_MEM_USED:-3.54GiB / 23.4GiB}" ;;
  "volume inspect") [ -n "$STUB_VOLUME" ] || exit 1 ;;
esac
exit 0
"""
K3D_STUB = """#!/bin/sh
echo "k3d $*" >> "$STUB_LOG"
case "$1 $2" in
  "cluster get") [ -n "$STUB_CLUSTER" ] || exit 1 ;;
  "registry list") [ -n "$STUB_REGISTRY" ] && echo "k3d-ace-registry" ;;
esac
exit 0
"""
KUBECTL_STUB = """#!/bin/sh
echo "kubectl $*" >> "$STUB_LOG"
case "$*" in
  *Ready*) echo "${STUB_READY:-True}" ;;
  *kubeletVersion*) echo "v1.37.1+k3s1" ;;
esac
exit 0
"""


def _run(
    tmp_path: Path,
    *args: str,
    tools: tuple[str, ...] = TOOLS,
    env_file: bool = True,
    **stub_env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    bodies = {"docker": DOCKER_STUB, "k3d": K3D_STUB, "kubectl": KUBECTL_STUB}
    for tool in tools:
        path = bin_dir / tool
        path.write_text(bodies.get(tool, "#!/bin/sh\nexit 0\n"))
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    dotenv = tmp_path / "dotenv"
    if env_file:
        dotenv.write_text("OPENCODE_KEY=sk-secret-value-never-shown\n")
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "ENV_FILE": str(dotenv),
        **stub_env,
    }
    result = subprocess.run(
        ["make", "-s", *args], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result, log.read_text().splitlines()


def _config() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(CONFIG.read_text())
    return config


def test_config_matches_spike_image_and_args() -> None:
    spike = yaml.safe_load(SPEC_CONFIG.read_text())
    ace = _config()
    assert ace["metadata"]["name"] == "ace"
    assert ace["image"] == spike["image"]
    assert ace["servers"] == spike["servers"] and ace["agents"] == spike["agents"]
    assert ace["options"]["k3s"]["extraArgs"] == spike["options"]["k3s"]["extraArgs"]
    assert [v["volume"].split(":", 1)[1] for v in ace["volumes"]] == ["/var/lib/ate"]
    assert "spike" not in CONFIG.read_text()


def test_config_has_registry_and_own_volume() -> None:
    ace = _config()
    assert ace["registries"]["create"]["name"]
    assert ace["volumes"][0]["volume"].startswith("ace-ate:")


def test_config_maps_web_and_dex_ports_through_the_load_balancer() -> None:
    ports = _config()["ports"]
    mapped = {p["port"].split(":")[0]: p for p in ports}
    assert set(mapped) == {"15180", "15656"}
    for p in ports:
        assert p["nodeFilters"] == ["loadbalancer"]
        host, node = p["port"].split(":")
        assert 30000 <= int(node) <= 32767, host


def test_host_ports_differ_from_playwright_defaults() -> None:
    defaults = set(re.findall(r'\?\? "(\d+)"', PLAYWRIGHT.read_text()))
    assert {"18080", "15173", "15556"} <= defaults
    host_ports = {p["port"].split(":")[0] for p in _config()["ports"]}
    assert not host_ports & defaults


def test_recipes_and_platform_scripts_never_name_the_spike_cluster() -> None:
    makefile = (ROOT / "Makefile").read_text()
    for target in ("up", "down", "status", "dev"):
        match = re.search(rf"^{target}:.*\n((?:\t.*\n?)*)", makefile, re.M)
        if match:
            assert "spike" not in match.group(0), target
    for script in (ROOT / "platform").rglob("*"):
        if script.is_file() and script.suffix in {".sh", ".yaml", ".py"}:
            assert "ace-spike" not in script.read_text(), script


def test_cluster_name_is_one_constant() -> None:
    code = "\n".join(
        line
        for line in CLUSTER_SCRIPT.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert len(re.findall(r"""CLUSTER="?ace"?""", code)) == 1
    assert not re.search(r"""['" ]ace['" ]""", code.replace('CLUSTER="ace"', ""))


def test_make_up_creates_cluster_from_platform_config(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")
    assert result.returncode == 0, result.stderr
    create = [c for c in calls if c.startswith("k3d cluster create")]
    assert len(create) == 1 and "platform/ace-cluster.yaml" in create[0]


def test_make_up_twice_does_not_recreate(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_CLUSTER="1")
    assert result.returncode == 0, result.stderr
    assert not [c for c in calls if "cluster create" in c]
    assert "already exists" in result.stdout + result.stderr


def test_preflight_names_missing_tool_and_creates_nothing(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", tools=("docker", "kubectl", "helm", "jq"))
    assert result.returncode != 0
    assert "k3d" in result.stdout + result.stderr
    assert not [c for c in calls if "cluster create" in c]


def test_preflight_names_missing_env_file(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", env_file=False)
    assert result.returncode != 0
    assert ".env" in result.stdout + result.stderr
    assert not [c for c in calls if "cluster create" in c]


def test_preflight_names_low_memory_and_the_number_seen(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", STUB_MEM_TOTAL="8589934592", STUB_MEM_USED="3GiB / 8GiB")
    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert "memory" in out.lower() and "5.0" in out
    assert not [c for c in calls if "cluster create" in c]


def test_env_file_values_never_reach_output(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "up")
    assert "sk-secret" not in result.stdout + result.stderr
    code = CLUSTER_SCRIPT.read_text() + (ROOT / "platform/preflight.sh").read_text()
    assert not re.search(r"\b(cat|source|grep|head|sed)\b[^\n#]*ENV_FILE", code)
    assert not re.search(r"^\s*\.\s+.*ENV_FILE", code, re.M)


def test_status_prints_ok_lines(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "status", STUB_CLUSTER="1")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 3 and all(line.startswith("ok") for line in lines)
    assert "v1.37.1+k3s1" in lines[2]


def test_status_fails_when_cluster_missing(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "status")
    assert result.returncode != 0
    assert any(line.startswith("FAIL") for line in result.stdout.splitlines())


def test_status_fails_when_node_not_ready(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "status", STUB_CLUSTER="1", STUB_READY="False")
    assert result.returncode != 0
    assert "FAIL" in result.stdout


def test_down_deletes_cluster_registry_and_volume(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "down", STUB_CLUSTER="1", STUB_REGISTRY="1", STUB_VOLUME="1")
    assert result.returncode == 0, result.stderr
    assert "k3d cluster delete ace" in calls
    assert "k3d registry delete k3d-ace-registry" in calls
    assert "docker volume rm ace-ate" in calls
    assert not any("spike" in c for c in calls)


def test_down_exits_zero_when_already_gone(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "down")
    assert result.returncode == 0, result.stderr
    assert not [c for c in calls if " delete" in c or "volume rm" in c]
