"""The README tells a developer what to install, the commands, and the Docker memory needed."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
SPIKE_LOG = (ROOT / "docs/spike-log.md").read_text()
DOCUMENTED_TARGETS = {"up", "status", "dev", "down"}


def test_readme_lists_prerequisites() -> None:
    for tool in ("Docker Desktop", "k3d", "kubectl", "helm", "jq", "openssl", "Tilt"):
        assert tool in README, tool
    assert "CPUs" in README
    assert "kubectl-ate" in README


def test_readme_names_env_example_variables_without_values() -> None:
    names = re.findall(r"^([A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M)
    assert names, "no variables in .env.example"
    for name in names:
        assert name in README, name
    assert not re.search(r"(OPENCODE_KEY|ANTHROPIC_API_KEY)=\S", README)
    assert "sk-" not in README
    assert "next `make up`" in README


def test_readme_gives_urls_ports_and_demo_sign_in() -> None:
    for text in (
        "http://127.0.0.1:15180/",
        "http://dex.ace.localhost:15656/dex",
        "15180",
        "15656",
        "18080",
        "15173",
        "15556",
        "demo-password",
    ):
        assert text in README, text
    config = (ROOT / "platform/dex/config.yaml").read_text()
    for email in re.findall(r"email: (\S+)", config):
        assert email in README, email
    assert "demo only" in README.lower()


def test_readme_states_docker_memory_and_spike_log_records_measurement() -> None:
    for text in ("900 MiB", "1.5 GiB", "3.44 GiB", "docker stats --no-stream"):
        assert text in README, text
    match = re.search(r"measured k3d-ace node total: ([0-9.]+) GiB", README)
    assert match, "README lacks 'measured k3d-ace node total: N GiB'"
    assert re.search(r"20\d\d-\d\d-\d\d", README)
    assert f"{match.group(1)} GiB" in SPIKE_LOG.split("## 17.")[1].split("\n## 18.")[0]


def test_readme_says_make_down_removes_only_ace() -> None:
    assert re.search(r"`make down`[^\n]*only the `ace` cluster", README)


def test_every_make_target_in_readme_is_listed_by_make_help() -> None:
    help_out = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    listed = {line.split()[0] for line in help_out.splitlines() if line.strip()}
    named = set(re.findall(r"`make ([a-z_-]+)`", README))
    assert DOCUMENTED_TARGETS <= named
    assert named <= listed, named - listed
