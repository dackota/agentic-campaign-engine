"""`make up` builds, pushes, and installs our app; `make status` reports it. Offline, on stubs."""

import re
from pathlib import Path

from tests.tooling.platform_stubs import ROOT
from tests.tooling.platform_stubs import run_make as _run

TILTFILE = ROOT / "Tiltfile"
APP_STEP = ROOT / "platform/app.sh"
REGISTRY_HOST = "localhost:62546"  # from the docker stub's `docker port`
COMPONENTS = ("api", "worker", "fake-marketo", "fake-cms", "fake-s3", "web", "postgres", "temporal")


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _up(tmp_path: Path, build_fails: bool = False) -> tuple[int, list[str], str]:
    # The docker stub fails a build when STUB_BUILD_FAIL is non-empty.
    build_fail = "1" if build_fails else ""
    result, calls = _run(
        tmp_path, "up", STUB_CLUSTER="1", STUB_INSTALLED="1", STUB_BUILD_FAIL=build_fail
    )
    return result.returncode, calls, result.stderr


def _docker(calls: list[str], verb: str) -> list[str]:
    return [c for c in calls if c.startswith(f"docker {verb} ")]


def test_up_builds_both_images_pushes_to_local_registry_and_installs_release(
    tmp_path: Path,
) -> None:
    code, calls, err = _up(tmp_path)
    assert code == 0, err
    builds = _docker(calls, "build")
    assert any("apps/web/Dockerfile" in b for b in builds)
    assert any("apps/python.Dockerfile" in b for b in builds)
    pushes = _docker(calls, "push")
    assert len(pushes) == 2
    (helm,) = [c for c in calls if "upgrade" in c and "--install" in c]
    assert "--kube-context k3d-ace" in helm and "charts/ace" in helm
    assert re.search(r"upgrade --install ace\b", helm.replace("--kube-context k3d-ace ", ""))
    assert "--namespace ace" in helm
    for image in ("ace-web", "ace-python"):
        assert f"ace-registry:5000/{image}" in helm
    # The tag follows the built image, so a changed image rolls the pods.
    assert calls.index(pushes[-1]) < calls.index(helm)


def test_app_step_runs_after_the_platform_steps(tmp_path: Path) -> None:
    code, calls, err = _up(tmp_path)
    assert code == 0, err
    last_platform = max(i for i, c in enumerate(calls) if "wait" in c and "agent/" in c)
    first_build = min(i for i, c in enumerate(calls) if c.startswith("docker build"))
    assert last_platform < first_build


def test_web_build_reads_the_issuer_constant(tmp_path: Path) -> None:
    code, calls, err = _up(tmp_path)
    assert code == 0, err
    issuer = (ROOT / "platform/oidc-issuer.txt").read_text().strip()
    (web,) = [b for b in _docker(calls, "build") if "apps/web/Dockerfile" in b]
    assert f"VITE_OIDC_ISSUER={issuer}" in web
    assert "oidc-issuer.txt" in _code(APP_STEP) and issuer not in _code(APP_STEP)


def test_install_waits_for_rollout(tmp_path: Path) -> None:
    _, calls, _ = _up(tmp_path)
    (helm,) = [c for c in calls if "upgrade" in c and "--install" in c]
    assert "--wait" in helm and "--timeout" in helm


def test_build_failure_stops_up_before_helm(tmp_path: Path) -> None:
    code, calls, _ = _up(tmp_path, build_fails=True)
    assert code != 0
    assert not [c for c in calls if "upgrade" in c and "--install" in c]
    assert not _docker(calls, "push")


def test_pushes_target_only_the_local_registry(tmp_path: Path) -> None:
    _, calls, _ = _up(tmp_path)
    for push in _docker(calls, "push"):
        assert push.split()[-1].startswith(f"{REGISTRY_HOST}/"), push
    assert "ghcr.io" not in _code(APP_STEP)


def test_nothing_references_ghcr_dackota() -> None:
    for path in (
        ROOT / "Makefile",
        TILTFILE,
        APP_STEP,
        *(ROOT / "platform").glob("*.sh"),
        *(ROOT / "charts").rglob("*.yaml"),
    ):
        assert "ghcr.io/dackota" not in path.read_text(), path


def test_release_name_matches_the_tiltfile() -> None:
    tilt = re.search(r"^RELEASE\s*=\s*['\"]([\w-]+)['\"]", _code(TILTFILE), re.M)
    step = re.search(r"^RELEASE=\"?([\w-]+)\"?", _code(APP_STEP), re.M)
    namespace = re.search(r"^NAMESPACE=\"?([\w-]+)\"?", _code(APP_STEP), re.M)
    assert tilt and step and namespace
    assert tilt.group(1) == step.group(1) == "ace"
    assert namespace.group(1) == "ace"


def test_second_up_exits_zero_and_upgrades_the_same_release(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, _, _ = _up(tmp_path / "a")
    second, calls, err = _up(tmp_path / "b")
    assert first == 0 and second == 0, err
    assert [c for c in calls if "upgrade" in c and "--install" in c]
    assert not [c for c in calls if "uninstall" in c or "delete" in c and "secret" in c]


def test_status_reports_each_app_component(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "status", STUB_CLUSTER="1", STUB_INSTALLED="1")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    for name in COMPONENTS:
        assert any(line.startswith("ok") and f"app {name}" in line for line in lines), name
    assert all(
        "--context k3d-ace" in c and "-n ace" in c
        for c in calls
        if "rollout status" in c and "deployment/api" in c
    )


def test_status_fails_on_a_stuck_app_rollout(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        "status",
        STUB_CLUSTER="1",
        STUB_INSTALLED="1",
        STUB_ROLLOUT_FAIL="deployment/temporal",
    )
    assert result.returncode != 0
    lines = result.stdout.splitlines()
    assert any(line.startswith("FAIL") and "app temporal" in line for line in lines)
    assert any(line.startswith("ok") and "app api" in line for line in lines)
