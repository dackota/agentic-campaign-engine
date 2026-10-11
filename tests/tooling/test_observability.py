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


def test_kagent_and_gateway_export_to_the_collector(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", "FULL=1")

    assert result.returncode == 0, result.stderr
    kagent = next(c for c in calls if c.startswith("helm") and " upgrade" in c and "/kagent " in c)
    assert "--reuse-values" in kagent
    assert "otel.traces.enabled=true" in kagent
    assert f"otel.exporter.otlp.endpoint={COLLECTOR_ENDPOINT}" in kagent
    assert "otel.exporter.otlp.protocol=http/protobuf" in kagent
    policies = [d for d in _applied(tmp_path) if d.get("kind") == "AgentgatewayPolicy"]
    tracing = [p for p in policies if "tracing" in p["spec"].get("frontend", {})]  # type: ignore[attr-defined]
    assert tracing, "a gateway policy with frontend tracing"


def test_the_app_gets_the_collector_endpoint_only_with_full(tmp_path: Path) -> None:
    _, with_full = _run(tmp_path, "up", "FULL=1")
    plain = tmp_path / "plain"
    plain.mkdir()
    _, without = _run(plain, "up")

    assert any(
        "otel.endpoint=" + COLLECTOR_ENDPOINT in c for c in with_full if c.startswith("helm")
    )
    assert not any("otel.endpoint" in c for c in without)
