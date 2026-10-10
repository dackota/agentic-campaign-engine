"""The web image: pinned bases, build argument, and an /api proxy that starts without the API."""

import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps/web/Dockerfile"
NGINX = ROOT / "apps/web/nginx.conf.template"
PINS = ROOT / "docs/pinned-versions.md"


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_base_images_are_pinned_by_digest_listed_in_pinned_versions() -> None:
    froms = re.findall(r"^FROM\s+(\S+)", _code(DOCKERFILE), re.M)
    assert froms, "no FROM lines"
    pins = PINS.read_text()
    for image in froms:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image
        assert image.split("@")[1] in pins, image


def test_image_takes_oidc_issuer_build_arg_and_builds_the_app() -> None:
    code = _code(DOCKERFILE)
    assert re.search(r"^ARG VITE_OIDC_ISSUER\b", code, re.M)
    assert re.search(r"^ARG VITE_OIDC_CLIENT_ID\b", code, re.M)
    assert re.search(r"pnpm --filter web exec vite build", code)
    assert "--frozen-lockfile" in code


def test_proxy_strips_prefix_and_does_not_buffer_sse() -> None:
    conf = _code(NGINX)
    assert re.search(r"location\s+/api/", conf)
    assert re.search(r"rewrite\s+\^/api/\(\.\*\)\$\s+/\$1\s+break", conf)
    assert re.search(r"proxy_buffering\s+off", conf)
    assert re.search(r"proxy_http_version\s+1\.1", conf)
    assert "${API_HOST}" in conf and "${API_PORT}" in conf


def test_proxy_resolves_api_at_request_time_so_it_starts_without_the_api() -> None:
    conf = _code(NGINX)
    # A literal host in proxy_pass is resolved at startup and kills nginx when the Service
    # is missing. A resolver plus a variable defers the lookup to the first request.
    assert re.search(r"resolver\s+\$\{DNS_RESOLVER\}", conf)
    assert re.search(r"set\s+\$api_upstream\s+http://\$\{API_HOST\}", conf)
    assert re.search(r"proxy_pass\s+\$api_upstream\s*;", conf)


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="needs a Docker daemon")
def test_image_starts_without_api_and_serves_app() -> None:
    tag = f"ace-web-test:{uuid.uuid4().hex[:8]}"
    name = f"ace-web-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "build", "-f", "apps/web/Dockerfile", "-t", tag, "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-e",
                "API_HOST=api.missing.invalid",
                "-e",
                "API_PORT=8000",
                "-e",
                "DNS_RESOLVER=127.0.0.11",
                tag,
            ],
            check=True,
            capture_output=True,
        )
        script = (
            "for i in 1 2 3 4 5 6 7 8 9 10; do "
            "wget -qO- http://127.0.0.1:8080/ | grep -q '<div id=\"root\">' && exit 0; "
            "sleep 1; done; exit 1"
        )
        probe = subprocess.run(
            ["docker", "exec", name, "sh", "-c", script], capture_output=True, text=True
        )
        assert probe.returncode == 0, probe.stderr
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "rmi", tag], capture_output=True)
