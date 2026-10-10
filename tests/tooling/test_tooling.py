"""The developer command line is the seam: make, pre-commit config, CI workflow."""

import json
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
    for target in ("help", "lint", "fmt", "test", "up", "down"):
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
