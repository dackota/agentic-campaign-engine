"""`make up FULL=1` adds the collector and grafana/otel-lgtm, and points kagent and the
gateway at the collector. Checked offline against stub kubectl and helm programs."""

from pathlib import Path

import yaml

from tests.tooling.platform_stubs import ROOT
from tests.tooling.platform_stubs import run_make as _run

OBSERVABILITY = ROOT / "manifests/observability"
COLLECTOR_ENDPOINT = "http://otel-collector.observability.svc.cluster.local:4318"
LGTM_IMAGE = "grafana/otel-lgtm"


def _applied(tmp_path: Path) -> list[dict[str, object]]:
    log = tmp_path / "calls.log.applied"
    if not log.exists():
        return []
    return [d for d in yaml.safe_load_all(log.read_text()) if d]


def test_make_up_full_installs_collector_and_lgtm(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", "FULL=1")

    assert result.returncode == 0, result.stderr
    assert any("apply" in c and "manifests/observability" in c for c in calls)
    images = " ".join(
        c["image"]
        for d in _applied(tmp_path)
        if d.get("kind") == "Deployment"
        for c in d["spec"]["template"]["spec"]["containers"]  # type: ignore[index]
    )
    assert LGTM_IMAGE in images
    assert "opentelemetry-collector" in images


def test_make_up_without_full_skips_observability(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")

    assert result.returncode == 0, result.stderr
    assert not any("observability" in c for c in calls)


def test_kagent_installs_with_tracing_on_when_full(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", "FULL=1")

    assert result.returncode == 0, result.stderr
    install = next(c for c in calls if c.startswith("SPIKE install.sh"))
    assert "OTEL=set" in install
    assert not any(c.startswith("helm") and " upgrade kagent " in c for c in calls)


def test_kagent_install_script_sets_the_otel_values_once() -> None:
    text = (ROOT / "scripts/spike/install.sh").read_text()

    assert text.count("otel.traces.enabled=true") == 1
    assert "ACE_OTEL_ENDPOINT" in text


def test_gateway_traces_go_to_the_collector() -> None:
    docs = list(yaml.safe_load_all((OBSERVABILITY / "gateway-tracing.yaml").read_text()))
    policy = next(d for d in docs if d["kind"] == "AgentgatewayPolicy")
    grant = next(d for d in docs if d["kind"] == "ReferenceGrant")

    tracing = policy["spec"]["frontend"]["tracing"]
    assert tracing["backendRef"]["name"] == "otel-collector"
    assert tracing["backendRef"]["namespace"] == grant["metadata"]["namespace"] == "observability"


def test_every_copy_of_the_collector_endpoint_agrees() -> None:
    assert COLLECTOR_ENDPOINT in (ROOT / "Makefile").read_text()


def test_a_cluster_with_the_platform_still_gets_kagent_tracing_on_full(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", "FULL=1", STUB_INSTALLED="1")

    assert result.returncode == 0, result.stderr
    assert any(c.startswith("SPIKE install.sh") and "OTEL=set" in c for c in calls)


def test_the_app_gets_the_collector_endpoint_only_with_full(tmp_path: Path) -> None:
    _, with_full = _run(tmp_path, "up", "FULL=1")
    plain = tmp_path / "plain"
    plain.mkdir()
    _, without = _run(plain, "up")

    assert any(
        "otel.endpoint=" + COLLECTOR_ENDPOINT in c for c in with_full if c.startswith("helm")
    )
    assert not any("otel.endpoint" in c for c in without)
