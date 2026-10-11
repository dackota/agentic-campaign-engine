"""The publish workflow: on push to main only, push both images to GHCR, sign each pushed
digest with the cosign key from Actions secrets (no public transparency log), verify it with
the committed cosign.pub, keep the packages private, and list image@sha256 lines."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-images.yml"
PINS = ROOT / "docs/pinned-versions.md"
SOURCES = ROOT / "docs/sources.md"
PREFIX = "ghcr.io/dackota/agentic-campaign-engine"
IMAGES = ("ace-python", "ace-web")


def _workflow() -> dict[Any, Any]:
    assert WORKFLOW.is_file(), "no publish workflow: .github/workflows/publish-images.yml"
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _triggers() -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = _workflow().get("on", _workflow().get(True))
    assert isinstance(triggers, dict)
    return triggers


def _jobs() -> dict[str, Any]:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps() -> list[dict[str, Any]]:
    return [step for job in _jobs().values() for step in job["steps"]]


def _runs() -> str:
    """Every `run` script, comment lines dropped."""
    return "\n".join(
        line
        for step in _steps()
        for line in str(step.get("run", "")).splitlines()
        if not line.lstrip().startswith("#")
    )


def _steps_running(command: str) -> list[dict[str, Any]]:
    return [step for step in _steps() if command in str(step.get("run", ""))]


def test_triggers_on_push_to_main_only() -> None:
    triggers = _triggers()
    assert set(triggers) == {"push"}
    assert triggers["push"]["branches"] == ["main"]


def test_job_runs_only_on_main() -> None:
    for job in _jobs().values():
        condition = job.get("if", "")
        assert "github.ref == 'refs/heads/main'" in condition
        assert "github.event_name == 'push'" in condition


def test_permissions_are_the_minimum() -> None:
    assert _workflow()["permissions"] == {"contents": "read", "packages": "write"}
    for job in _jobs().values():
        assert "permissions" not in job or job["permissions"] == {
            "contents": "read",
            "packages": "write",
        }
    assert "id-token" not in WORKFLOW.read_text()


def test_logs_in_to_ghcr_with_the_job_token() -> None:
    logins = _steps_running("docker login")
    assert len(logins) == 1
    login = logins[0]
    assert "ghcr.io" in login["run"]
    assert "--password-stdin" in login["run"]
    assert login["env"]["GHCR_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert "secrets." not in login["run"]


def test_pushes_both_images_and_records_digests() -> None:
    runs = _runs()
    assert "apps/python.Dockerfile" in runs
    assert "apps/web/Dockerfile" in runs
    assert re.search(r"--build-arg\s+\"?VITE_OIDC_ISSUER=", runs)
    assert "platform/oidc-issuer.txt" in runs
    assert "docker push" in runs
    assert "RepoDigests" in runs
    workflow = WORKFLOW.read_text()
    assert PREFIX in workflow
    for image in IMAGES:
        assert image in workflow


def test_signs_each_digest_with_the_env_key_and_no_tlog_upload() -> None:
    signs = _steps_running("cosign sign")
    assert len(signs) == 1
    sign = signs[0]
    assert "--key env://COSIGN_PRIVATE_KEY" in sign["run"]
    assert "--tlog-upload=false" in sign["run"]
    # cosign v3 refuses --tlog-upload=false while it reads the TUF signing config.
    assert "--use-signing-config=false" in sign["run"]
    assert "@sha256:" in sign["run"] or "digests" in sign["run"]
    assert sign["env"]["COSIGN_PRIVATE_KEY"] == "${{ secrets.COSIGN_PRIVATE_KEY }}"
    assert sign["env"]["COSIGN_PASSWORD"] == "${{ secrets.COSIGN_PASSWORD }}"


def test_verifies_with_the_committed_public_key_ignoring_the_tlog() -> None:
    verifies = _steps_running("cosign verify")
    assert len(verifies) == 1
    assert "--key cosign.pub" in verifies[0]["run"]
    assert "--insecure-ignore-tlog=true" in verifies[0]["run"]
    job_steps = next(iter(_jobs().values()))["steps"]
    sign_at = job_steps.index(_steps_running("cosign sign")[0])
    assert job_steps.index(verifies[0]) > sign_at


def test_secrets_reach_cosign_only_through_env() -> None:
    for step in _steps():
        run = str(step.get("run", ""))
        assert "secrets." not in run
        assert not re.search(r"\$\{\{[^}]*\}\}", run), "expressions in run scripts go through env"
        assert not re.search(r"(echo|printf|cat)\b[^\n|]*\$\{?COSIGN_(PRIVATE_KEY|PASSWORD)", run)
        assert "set -x" not in run
    for step in _steps():
        for value in step.get("with", {}).values():
            assert "secrets." not in str(value)


def test_cosign_installer_is_pinned_by_commit_sha() -> None:
    installers = [
        s for s in _steps() if str(s.get("uses", "")).startswith("sigstore/cosign-installer")
    ]
    assert len(installers) == 1
    assert re.fullmatch(r"sigstore/cosign-installer@[0-9a-f]{40}", installers[0]["uses"])
    assert re.fullmatch(r"v\d+\.\d+\.\d+", installers[0]["with"]["cosign-release"])


def test_cosign_version_and_installer_sha_match_the_pins() -> None:
    installer = next(
        s for s in _steps() if str(s.get("uses", "")).startswith("sigstore/cosign-installer")
    )
    sha = installer["uses"].split("@")[1]
    version = installer["with"]["cosign-release"]
    pins = PINS.read_text()
    assert sha in pins
    assert re.search(rf"\|\s*cosign\b[^\n]*\|\s*`?{re.escape(version)}`?", pins)
    sources = SOURCES.read_text()
    for flag in (
        "--key env://",
        "--tlog-upload=false",
        "--insecure-ignore-tlog=true",
        "--use-signing-config=false",
    ):
        assert flag in sources, flag
    assert version in sources


def test_checks_package_visibility_is_private_and_never_changes_it() -> None:
    runs = _runs()
    assert "/users/dackota/packages/container/" in runs
    assert ".visibility" in runs
    assert "private" in runs
    assert not re.search(r"(-X|--method)\s+(PATCH|PUT|POST)", runs)
    assert not re.search(r"-[fF]\s+visibility", runs)
    job_steps = next(iter(_jobs().values()))["steps"]
    push_at = job_steps.index(_steps_running("docker push")[0])
    check_at = job_steps.index(_steps_running(".visibility")[0])
    assert check_at > push_at


def test_summary_lists_each_image_by_digest() -> None:
    summary = _steps_running("GITHUB_STEP_SUMMARY")
    assert len(summary) == 1
    job_steps = next(iter(_jobs().values()))["steps"]
    verify_at = job_steps.index(_steps_running("cosign verify")[0])
    assert job_steps.index(summary[0]) > verify_at
    assert "digests" in summary[0]["run"]
