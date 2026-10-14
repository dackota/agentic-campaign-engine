"""The developer command line is the seam: make, pre-commit config, CI workflow."""

import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOMES = [
    "apps/api",
    "apps/worker",
    "apps/web",
    "services/render",
    "services/fakes",
    "services/mcp",
    "charts",
    "platform",
    "agents",
    "evals",
    "docs",
]


def test_make_help_lists_targets() -> None:
    out = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    for target in ("help", "lint", "fmt", "test", "up", "down", "status"):
        assert any(line.split()[:1] == [target] for line in out.splitlines()), target


def test_each_home_directory_exists() -> None:
    for home in HOMES:
        assert (ROOT / home).is_dir(), home


def test_python_tooling_is_declared() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = " ".join(pyproject["dependency-groups"]["dev"])
    for tool in ("ruff", "mypy", "pytest"):
        assert tool in dev
    assert (ROOT / "uv.lock").exists()


def test_yaml_tooling_is_declared() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = [d.lower() for d in pyproject["dependency-groups"]["dev"]]
    for package in ("pyyaml", "types-pyyaml"):
        assert any(d.startswith(package) for d in dev), package
    lock = (ROOT / "uv.lock").read_text()
    assert 'name = "types-pyyaml"' in lock
    # The gateway tests read manifests through this shared module.
    gateway_files = (ROOT / "tests/tooling/gateway_files.py").read_text()
    assert "import yaml\n" in gateway_files
    assert "type: ignore" not in gateway_files


def test_web_app_tooling_is_declared() -> None:
    pkg = json.loads((ROOT / "apps/web/package.json").read_text())
    deps = {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}
    for tool in ("eslint", "@playwright/test"):
        assert tool in deps
    assert (ROOT / "pnpm-lock.yaml").exists()


def test_pre_commit_runs_lint_and_format() -> None:
    text = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "ruff-check" in text
    assert "ruff-format" in text
    assert "eslint" in text


def test_ci_runs_make_lint_on_pull_request() -> None:
    text = (ROOT / ".github/workflows/lint.yml").read_text()
    assert "pull_request" in text
    assert "make lint" in text


def test_pre_commit_hooks_match_ci_and_install_web_deps() -> None:
    text = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "ruff format --check" in text
    assert "--fix" not in text
    assert "pnpm install --frozen-lockfile" in text
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    assert any(d.startswith("pre-commit") for d in dev)


def test_ci_runs_make_test_on_pull_request() -> None:
    text = (ROOT / ".github/workflows/test.yml").read_text()
    assert "pull_request" in text
    assert "make test" in text


def test_ci_installs_a_pinned_checksummed_gitleaks_before_make_test() -> None:
    text = (ROOT / ".github/workflows/test.yml").read_text()
    install = text.index("gitleaks_")
    assert install < text.index("- run: make test")
    assert re.search(r"GITLEAKS_VERSION: \d+\.\d+\.\d+", text)
    assert re.search(r"GITLEAKS_SHA256: [0-9a-f]{64}", text)
    assert "sha256sum -c" in text


def test_make_test_runs_both_seams_with_pytest_on_four_workers() -> None:
    makefile = (ROOT / "Makefile").read_text()
    test_target = makefile.split("\ntest:", 1)[1].split("\n\n", 1)[0]
    assert "uv run pytest -n 4 --dist loadfile" in test_target
    assert "e2e" in test_target
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    assert any(d.startswith("pytest-xdist") for d in dev)
