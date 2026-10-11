"""The one Python image: API, worker, and fake Marketo with different commands, built from
every source root the tests put on the path."""

import re
import shutil
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps/python.Dockerfile"
PINS = ROOT / "docs/pinned-versions.md"
APP_DIR = "/app"


def _code() -> str:
    return "\n".join(
        line for line in DOCKERFILE.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _source_roots() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return [p for p in config["tool"]["pytest"]["ini_options"]["pythonpath"] if p != "."]


def test_base_images_are_pinned_by_digest_listed_in_pinned_versions() -> None:
    code = _code()
    images = re.findall(r"^FROM\s+(\S+)", code, re.M)
    images += re.findall(r"^COPY\s+--from=(\S+)", code, re.M)
    assert images, "no base images"
    pins = PINS.read_text()
    for image in images:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image
        assert image.split("@")[1] in pins, image


def test_image_copies_every_pythonpath_root_and_sets_pythonpath() -> None:
    code = _code()
    roots = _source_roots()
    assert set(roots) == {
        "apps/engine",
        "apps/api",
        "apps/worker",
        "services/fakes",
        "services/render",
    }
    for root in roots:
        top = root.split("/")[0]
        copied = re.search(rf"^COPY\s+(--\S+\s+)*{top}\s+{APP_DIR}/{top}\s*$", code, re.M)
        assert copied or re.search(rf"^COPY\s+(--\S+\s+)*{root}\s", code, re.M), root
    pythonpath = re.search(r"PYTHONPATH=(\S+)", code)
    assert pythonpath
    assert pythonpath.group(1).split(":") == [f"{APP_DIR}/{r}" for r in roots]
    assert re.search(r"uv sync --frozen --no-dev", code)
    assert re.search(r"^USER\s+\d+", code, re.M), "run as a numeric non-root user"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="needs a Docker daemon")
def test_image_builds_and_imports_every_entrypoint() -> None:
    tag = f"ace-python-test:{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "build", "-f", str(DOCKERFILE), "-t", tag, "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    try:
        script = (
            "import campaign_api.__main__, campaign_worker.__main__, fake_marketo.__main__, "
            "fake_cms.__main__, fake_s3.__main__, "
            "render_service.email, ace_engine.env, watchfiles"
        )
        result = subprocess.run(
            ["docker", "run", "--rm", tag, "python", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        missing = subprocess.run(
            ["docker", "run", "--rm", tag, "python", "-m", "campaign_worker"],
            capture_output=True,
            text=True,
        )
        assert missing.returncode != 0
        assert "ACE_" in missing.stderr
    finally:
        subprocess.run(["docker", "rmi", tag], capture_output=True)
