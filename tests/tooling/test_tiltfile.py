"""The Tiltfile is checked as text: contexts, extension, and how the chart is deployed."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TILTFILE = ROOT / "Tiltfile"
PINS = ROOT / "docs/pinned-versions.md"


def _code() -> str:
    return "\n".join(
        line for line in TILTFILE.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_tiltfile_allows_only_k3d_ace() -> None:
    code = _code()
    contexts = re.findall(r"k3d-[\w-]+", code)
    assert contexts and set(contexts) == {"k3d-ace"}
    assert "ace-spike" not in code
    assert re.search(r"allow_k8s_contexts\(\s*['\"]k3d-ace['\"]\s*\)", code)


def test_tiltfile_uses_helm_resource_not_helm() -> None:
    code = _code()
    assert "helm_resource(" in code
    assert re.search(r"ext://helm_resource", code)
    assert not re.search(r"(?<![\w_])helm\(", code)


def test_tiltfile_builds_web_image_and_wires_it_to_the_chart() -> None:
    code = _code()
    assert re.search(r"docker_build\(\s*['\"]ace-web['\"]", code)
    assert "apps/web/Dockerfile" in code
    assert "VITE_OIDC_ISSUER" in code
    assert "image_deps" in code and "image_keys" in code
    assert "web.image.repository" in code and "web.image.tag" in code
    assert "charts/ace" in code


def test_release_name_and_namespace_match_the_chart_constants() -> None:
    code = _code()
    assert re.search(r"^RELEASE\s*=\s*['\"]ace['\"]", code, re.M)
    assert re.search(r"helm_resource\(\s*RELEASE\b", code)
    assert re.search(r"^NAMESPACE\s*=\s*['\"]ace['\"]", code, re.M)
    assert re.search(r"namespace\s*=\s*NAMESPACE", code)
    assert "--create-namespace" in code


def test_extension_repo_is_pinned_by_commit() -> None:
    code = _code()
    ref = re.search(r"ref\s*=\s*['\"]([0-9a-f]{40})['\"]", code)
    assert ref, "tilt-extensions must be pinned by commit sha"
    assert ref.group(1) in PINS.read_text()
