"""Dashboards and alert rules as code: Grafana dashboards and alert rules live in the repo
and `make up FULL=1` provisions them into grafana/otel-lgtm; alerts reach the Campaign API's
webhook (the in-app banner and Slack); Honeycomb export is added only when its key is set.
Checked offline against stub kubectl and helm programs."""

import json
from pathlib import Path
from typing import Any

import yaml

from tests.tooling.platform_stubs import ROOT
from tests.tooling.platform_stubs import run_make as _run

OBSERVABILITY = ROOT / "manifests/observability"
GRAFANA = OBSERVABILITY / "grafana"
DASHBOARDS = GRAFANA / "dashboards"
DASHBOARD_NAMES = {"pipeline-health", "cost", "quality", "failovers"}
RULE_TITLES = {"run-failure-rate", "cost-spike", "eval-score-drop", "gateway-failover"}
# The metrics the stack exports: ours (apps/engine/ace_engine/metrics.py) and the span
# metrics the collector derives from every span.
KNOWN_METRICS = (
    "ace_runs_total",
    "ace_cost_dollars_total",
    "ace_eval_score_sum",
    "ace_eval_score_count",
    "traces_span_metrics_calls_total",
)
WEBHOOK_URL = "http://api.ace.svc.cluster.local:8000/alerts/webhook"
HONEYCOMB_VALUE = "hc-key-value-never-shown"
HONEYCOMB_ENV = f"OPENCODE_KEY=sk-secret-value-never-shown\nHONEYCOMB_API_KEY={HONEYCOMB_VALUE}\n"


def _alerting() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((GRAFANA / "alerting.yaml").read_text())
    return loaded


def _rules() -> list[dict[str, Any]]:
    return [r for g in _alerting()["groups"] for r in g["rules"]]


def _expressions(rule: dict[str, Any]) -> str:
    return " ".join(d["model"].get("expr", "") for d in rule["data"])


def _applied(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "calls.log.applied"
    return [d for d in yaml.safe_load_all(log.read_text()) if d] if log.exists() else []


def _collector_config(docs: list[dict[str, Any]]) -> dict[str, Any]:
    # The last one applied wins: the Honeycomb overlay replaces the base ConfigMap.
    cm = [
        d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "otel-collector"
    ][-1]
    config: dict[str, Any] = yaml.safe_load(cm["data"]["config.yaml"])
    return config


def _file_docs(path: Path) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _lgtm() -> dict[str, Any]:
    [deploy] = [
        d
        for d in _file_docs(OBSERVABILITY / "collector.yaml")
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "lgtm"
    ]
    return deploy


def test_four_dashboards_are_saved_in_the_repo() -> None:
    found = {p.stem: json.loads(p.read_text()) for p in DASHBOARDS.glob("*.json")}

    assert set(found) == DASHBOARD_NAMES
    for name, dashboard in found.items():
        assert dashboard["uid"] == f"ace-{name}"
        assert dashboard["title"]
        assert dashboard["panels"], name


def test_every_dashboard_panel_queries_a_metric_the_stack_exports() -> None:
    for path in DASHBOARDS.glob("*.json"):
        for panel in json.loads(path.read_text())["panels"]:
            exprs = [t["expr"] for t in panel["targets"]]
            assert exprs, (path.name, panel["title"])
            for expr in exprs:
                assert any(m in expr for m in KNOWN_METRICS), (path.name, expr)
            assert panel["datasource"]["uid"] == "prometheus"


def test_alert_rules_cover_the_four_signals() -> None:
    rules = _rules()

    assert {r["title"] for r in rules} == RULE_TITLES
    for rule in rules:
        assert rule["annotations"]["summary"], rule["title"]
        assert any(m in _expressions(rule) for m in KNOWN_METRICS), rule["title"]
        # No data (nothing ran yet) is not an alert.
        assert rule["noDataState"] == "OK", rule["title"]


def test_failover_alert_reads_calls_to_the_backup_provider() -> None:
    [rule] = [r for r in _rules() if r["title"] == "gateway-failover"]
    config = _collector_config(_file_docs(OBSERVABILITY / "collector.yaml"))

    assert "traces_span_metrics_calls_total" in _expressions(rule)
    assert "gen_ai_provider_name" in _expressions(rule)
    connector = config["connectors"]["spanmetrics"]
    assert "gen_ai.provider.name" in [d["name"] for d in connector["dimensions"]]
    assert "spanmetrics" in config["service"]["pipelines"]["traces"]["exporters"]
    assert "spanmetrics" in config["service"]["pipelines"]["metrics"]["receivers"]


def test_alerts_go_to_the_campaign_api_webhook_with_the_token() -> None:
    alerting = _alerting()
    [point] = alerting["contactPoints"]
    [receiver] = point["receivers"]

    assert receiver["type"] == "webhook"
    assert receiver["settings"]["url"] == WEBHOOK_URL
    assert receiver["settings"]["authorization_scheme"] == "Bearer"
    # The token comes from the container's environment, never from the file.
    assert receiver["settings"]["authorization_credentials"] == "$__env{ACE_ALERT_WEBHOOK_TOKEN}"
    assert alerting["policies"][0]["receiver"] == point["name"]


def test_grafana_gets_the_files_and_the_token() -> None:
    pod = _lgtm()["spec"]["template"]["spec"]
    container = pod["containers"][0]
    mounts = {m["mountPath"] for m in container["volumeMounts"]}
    env = {e["name"]: e for e in container["env"]}
    ref = env["ACE_ALERT_WEBHOOK_TOKEN"]["valueFrom"]["secretKeyRef"]

    assert "/otel-lgtm/grafana/conf/provisioning/alerting/ace.yaml" in mounts
    assert "/otel-lgtm/grafana/conf/provisioning/dashboards/ace.yaml" in mounts
    assert "/ace-dashboards" in mounts
    assert (ref["name"], ref["key"]) == ("alert-webhook", "token")
    assert not ref.get("optional")


def test_kustomization_lists_every_dashboard_and_the_rules() -> None:
    kustomization = yaml.safe_load((GRAFANA / "kustomization.yaml").read_text())
    files = {
        f.split("=", 1)[-1] for gen in kustomization["configMapGenerator"] for f in gen["files"]
    }

    assert {f"dashboards/{n}.json" for n in DASHBOARD_NAMES} <= files
    assert {"alerting.yaml", "dashboards.yaml"} <= files
    assert all((GRAFANA / f).exists() for f in files)
    assert kustomization["generatorOptions"]["disableNameSuffixHash"] is True


def test_make_up_full_provisions_the_dashboards_and_alert_rules(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up", "FULL=1")

    assert result.returncode == 0, result.stderr
    assert any(
        " apply -k " in c and str(GRAFANA) in c and "--context k3d-ace" in c for c in calls
    ), calls
    # The shared webhook token is made once, in both namespaces, and never put on a command line.
    created = [c for c in calls if " create secret" in c and "alert-webhook" in c]
    assert {"-n observability" in c for c in created} == {True, False}
    assert any("-n ace" in c for c in created)
    assert not any("--from-literal" in c for c in calls)


def test_make_up_without_full_provisions_nothing(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "up")

    assert result.returncode == 0, result.stderr
    assert not any("alert-webhook" in c or str(GRAFANA) in c for c in calls)


def test_honeycomb_exporter_only_when_its_key_is_set(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _run(plain, "up", "FULL=1")
    keyed = tmp_path / "keyed"
    keyed.mkdir()
    result, calls = _run(keyed, "up", "FULL=1", env_text=HONEYCOMB_ENV)

    assert result.returncode == 0, result.stderr
    without = _collector_config(_applied(plain))
    with_key = _collector_config(_applied(keyed))
    assert "otlp/honeycomb" not in without["exporters"]
    assert "honeycomb" not in json.dumps(without)
    assert with_key["exporters"]["otlp/honeycomb"]["endpoint"] == "api.honeycomb.io:443"
    assert with_key["exporters"]["otlp/honeycomb"]["headers"]["x-honeycomb-team"] == (
        "${env:HONEYCOMB_API_KEY}"
    )
    for pipeline in ("traces", "metrics"):
        assert "otlp/honeycomb" in with_key["service"]["pipelines"][pipeline]["exporters"]
        assert "otlp/honeycomb" not in without["service"]["pipelines"][pipeline]["exporters"]
    assert any(" create secret" in c and "honeycomb" in c for c in calls)


def test_honeycomb_overlay_is_the_base_config_plus_the_exporter() -> None:
    base = _collector_config(_file_docs(OBSERVABILITY / "collector.yaml"))
    overlay = _collector_config(_file_docs(OBSERVABILITY / "collector-honeycomb.yaml"))

    del overlay["exporters"]["otlp/honeycomb"]
    for pipeline in overlay["service"]["pipelines"].values():
        pipeline["exporters"].remove("otlp/honeycomb")

    assert overlay == base


def test_collector_reads_the_honeycomb_key_from_an_optional_secret() -> None:
    [deploy] = [
        d
        for d in _file_docs(OBSERVABILITY / "collector.yaml")
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "otel-collector"
    ]
    [env] = [
        e
        for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]
        if e["name"] == "HONEYCOMB_API_KEY"
    ]

    ref = env["valueFrom"]["secretKeyRef"]
    assert (ref["name"], ref["key"], ref["optional"]) == ("honeycomb", "api-key", True)


def test_no_key_value_reaches_a_command_line_or_a_manifest(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, "up", "FULL=1", env_text=HONEYCOMB_ENV)

    assert HONEYCOMB_VALUE not in "\n".join(calls)
    assert HONEYCOMB_VALUE not in yaml.safe_dump_all(_applied(tmp_path))
    for path in OBSERVABILITY.rglob("*"):
        if path.is_file():
            assert HONEYCOMB_VALUE not in path.read_text()
