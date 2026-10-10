"""The image build workflow: builds both images on PRs, never pushes, never logs in."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/images.yml"


def _workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _code() -> str:
    return "\n".join(
        line for line in WORKFLOW.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _triggers() -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = _workflow().get("on", _workflow().get(True))
    assert isinstance(triggers, dict)
    return triggers


def test_triggers_on_pull_request_with_path_filter() -> None:
    triggers = _triggers()
    assert set(triggers) == {"pull_request"}
    assert triggers["pull_request"]["paths"]


def test_path_filter_covers_image_inputs() -> None:
    paths = _triggers()["pull_request"]["paths"]
    for changed in (
        "apps/engine/x.py",
        "apps/api/x.py",
        "apps/worker/x.py",
        "services/fakes/x.py",
        "services/render/x.py",
        "apps/web/src/App.tsx",
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "apps/python.Dockerfile",
        "apps/web/Dockerfile",
        "platform/oidc-issuer.txt",
        ".github/workflows/images.yml",
    ):
        assert any(_matches(p, changed) for p in paths), changed


def _matches(pattern: str, path: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def test_builds_both_dockerfiles() -> None:
    code = _code()
    assert re.search(r"docker build\b[^\n]*apps/python\.Dockerfile", code) or re.search(
        r"apps/python\.Dockerfile", code
    )
    assert "apps/web/Dockerfile" in code
    assert code.count("docker build") + code.count("docker/build-push-action") >= 2


def test_web_build_passes_issuer_from_the_constant() -> None:
    code = _code()
    assert "platform/oidc-issuer.txt" in code
    assert re.search(r"--build-arg\s+\"?VITE_OIDC_ISSUER=", code)


def test_never_pushes_or_logs_in() -> None:
    code = _code()
    assert not re.search(r"push:\s*true", code)
    assert not re.search(r"--push\b", code)
    assert "docker push" not in code
    assert "docker login" not in code
    assert "docker/login-action" not in code
    assert "packages: write" not in code
    assert "GITHUB_TOKEN" not in code
    assert "secrets." not in code


def test_summary_lists_each_image_with_id() -> None:
    code = _code()
    assert "GITHUB_STEP_SUMMARY" in code
    assert "docker image inspect" in code or "--iidfile" in code
    assert "ace-python" in code
    assert "ace-web" in code
