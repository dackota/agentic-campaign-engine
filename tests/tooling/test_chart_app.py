"""The whole app in the chart: Postgres, Temporal, API, worker, fake Marketo, and the one app
Secret. Rendered with `helm template`, offline, where `lookup` finds nothing."""

import base64
import re
from pathlib import Path
from typing import Any

import yaml

from tests.tooling.chart_files import CHART, by_kind, raw_render, render

ROOT = Path(__file__).resolve().parents[2]
SECRET_TEMPLATE = CHART / "templates/secret.yaml"
SECRET_KEYS = {"postgres-password", "marketo-client-secret", "marketo-webhook-secret"}
PYTHON_COMPONENTS = {"api": "campaign_api", "worker": "campaign_worker"}
SECRET_WORDS = ("SECRET", "PASSWORD", "TOKEN", "KEY")


def _named(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    (doc,) = [d for d in by_kind(docs, kind) if d["metadata"]["name"] == name]
    return doc


def _container(deploy: dict[str, Any]) -> dict[str, Any]:
    (container,) = deploy["spec"]["template"]["spec"]["containers"]
    found: dict[str, Any] = container
    return found


def _env(deploy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in _container(deploy).get("env", [])}


def _values(deploy: dict[str, Any]) -> dict[str, str]:
    return {k: e["value"] for k, e in _env(deploy).items() if "value" in e}


def _secret(docs: list[dict[str, Any]]) -> dict[str, Any]:
    (secret,) = by_kind(docs, "Secret")
    return secret


def test_chart_deploys_every_app_component_with_a_service() -> None:
    docs = render()
    deployments = {d["metadata"]["name"] for d in by_kind(docs, "Deployment")}
    services = {d["metadata"]["name"] for d in by_kind(docs, "Service")}

    assert deployments == {
        "web",
        "api",
        "worker",
        "fake-marketo",
        "fake-cms",
        "fake-s3",
        "postgres",
        "temporal",
    }
    assert services == {"web", "api", "fake-marketo", "fake-cms", "fake-s3", "postgres", "temporal"}
    for name in services:
        svc = _named(docs, "Service", name)
        labels = _named(docs, "Deployment", name)["spec"]["template"]["metadata"]["labels"]
        assert svc["spec"]["selector"].items() <= labels.items(), name


def test_python_services_share_one_image_with_different_commands() -> None:
    docs = render("python.image.repository=reg/py", "python.image.tag=t9")
    commands = {}
    for name in ("api", "worker", "fake-marketo", "fake-cms", "fake-s3"):
        container = _container(_named(docs, "Deployment", name))
        assert container["image"] == "reg/py:t9", name
        commands[name] = tuple(container["command"])
    assert commands["api"] == ("python", "-m", "campaign_api")
    assert commands["worker"] == ("python", "-m", "campaign_worker")
    assert commands["fake-marketo"] == ("python", "-m", "fake_marketo")
    assert commands["fake-cms"] == ("python", "-m", "fake_cms")
    assert commands["fake-s3"] == ("python", "-m", "fake_s3")


def test_reload_value_wraps_python_commands_in_a_file_watcher() -> None:
    docs = render("python.reload=true")
    for name, module in (
        *PYTHON_COMPONENTS.items(),
        ("fake-marketo", "fake_marketo"),
        ("fake-cms", "fake_cms"),
        ("fake-s3", "fake_s3"),
    ):
        command = _container(_named(docs, "Deployment", name))["command"]
        assert command[0] == "watchfiles", name
        assert f"python -m {module}" in command, name
        assert "/app/apps" in command and "/app/services" in command, name


def test_postgres_and_temporal_keep_state_on_volumes() -> None:
    docs = render()
    claims = {d["metadata"]["name"] for d in by_kind(docs, "PersistentVolumeClaim")}
    for name in ("postgres", "temporal"):
        deploy = _named(docs, "Deployment", name)
        assert deploy["spec"]["strategy"]["type"] == "Recreate", name
        volumes = deploy["spec"]["template"]["spec"]["volumes"]
        used = {v["persistentVolumeClaim"]["claimName"] for v in volumes}
        assert used and used <= claims, name
        assert _container(deploy)["volumeMounts"], name
    temporal = _container(_named(docs, "Deployment", "temporal"))
    args = temporal["args"]
    assert args[:2] == ["server", "start-dev"]
    db_file = args[args.index("--db-filename") + 1]
    mount = temporal["volumeMounts"][0]["mountPath"]
    assert db_file.startswith(mount + "/")
    postgres = _named(docs, "Deployment", "postgres")
    pg_mount = _container(postgres)["volumeMounts"][0]["mountPath"]
    assert _values(postgres)["PGDATA"].startswith(pg_mount + "/")


def test_services_are_wired_by_service_names() -> None:
    docs = render()
    api = _values(_named(docs, "Deployment", "api"))
    worker = _values(_named(docs, "Deployment", "worker"))
    marketo = _values(_named(docs, "Deployment", "fake-marketo"))

    for env in (api, worker):
        assert env["ACE_DATABASE_URL"] == (
            "postgresql+psycopg://ace@postgres.ace.svc.cluster.local:5432/ace"
        )
        assert env["ACE_TEMPORAL_ADDRESS"] == "temporal.ace.svc.cluster.local:7233"
        assert env["ACE_MARKETO_URL"] == "http://fake-marketo.ace.svc.cluster.local:8000"
        assert env["ACE_MARKETO_CLIENT_ID"] == marketo["ACE_MARKETO_CLIENT_ID"]
        assert env["ACE_CMS_URL"] == "http://fake-cms.ace.svc.cluster.local:8000"
        assert env["ACE_S3_URL"] == "http://fake-s3.ace.svc.cluster.local:8000"
        assert env["ACE_S3_BUCKET"] == "ace-assets"
    assert marketo["ACE_MARKETO_WEBHOOK_URL"] == (
        "http://api.ace.svc.cluster.local:8000/webhooks/marketo"
    )
    assert api["ACE_OIDC_CLIENT_ID"] == "ace-web"
    assert "ACE_OIDC_ISSUER" not in worker and "ACE_OIDC_CLIENT_ID" not in worker
    ports = {
        name: _named(docs, "Service", name)["spec"]["ports"][0]["port"]
        for name in ("api", "fake-marketo", "fake-cms", "fake-s3", "postgres", "temporal")
    }
    assert ports == {
        "api": 8000,
        "fake-marketo": 8000,
        "fake-cms": 8000,
        "fake-s3": 8000,
        "postgres": 5432,
        "temporal": 7233,
    }


def test_worker_agent_url_is_a_value() -> None:
    default = _values(_named(render(), "Deployment", "worker"))["ACE_AGENT_URL"]
    assert default
    changed = _values(_named(render("worker.agentUrl=http://a:1"), "Deployment", "worker"))
    assert changed["ACE_AGENT_URL"] == "http://a:1"
    values = (CHART / "values.yaml").read_text()
    assert "#29" in values


def test_one_secret_holds_the_three_generated_values() -> None:
    first = _secret(render())
    second = _secret(render())

    assert set(first["data"]) == SECRET_KEYS
    for key in SECRET_KEYS:
        value = base64.b64decode(first["data"][key]).decode()
        assert len(value) >= 24 and value.isalnum(), key
        # Generated on each fresh render (no Secret for lookup to find): never a fixed value.
        assert first["data"][key] != second["data"][key], key


def test_secret_template_reuses_values_found_by_lookup() -> None:
    code = SECRET_TEMPLATE.read_text()
    assert re.search(r'lookup\s+"v1"\s+"Secret"\s+\.Release\.Namespace', code)
    assert "randAlphaNum" in code
    # Each key falls back to a fresh value only when the found Secret lacks it.
    assert re.search(r"\.data", code)


def test_secret_env_comes_only_from_secret_key_ref() -> None:
    docs = render()
    secret_name = _secret(docs)["metadata"]["name"]
    wanted = {
        "postgres": {"POSTGRES_PASSWORD"},
        "api": {"ACE_DATABASE_PASSWORD", "ACE_MARKETO_CLIENT_SECRET", "ACE_MARKETO_WEBHOOK_SECRET"},
        "worker": {
            "ACE_DATABASE_PASSWORD",
            "ACE_MARKETO_CLIENT_SECRET",
            "ACE_MARKETO_WEBHOOK_SECRET",
        },
        "fake-marketo": {"ACE_MARKETO_CLIENT_SECRET", "ACE_MARKETO_WEBHOOK_SECRET"},
    }
    for deploy in by_kind(docs, "Deployment"):
        env = _env(deploy)
        name = deploy["metadata"]["name"]
        secretish = {k for k in env if any(w in k for w in SECRET_WORDS)}
        assert secretish == wanted.get(name, set()), name
        for key in secretish:
            assert "value" not in env[key], (name, key)
            ref = env[key]["valueFrom"]["secretKeyRef"]
            assert ref["name"] == secret_name and ref["key"] in SECRET_KEYS, (name, key)


def test_render_and_values_hold_no_secret_literal() -> None:
    out = raw_render()
    docs = [d for d in yaml.safe_load_all(out) if d]
    secret_values = [base64.b64decode(v).decode() for v in _secret(docs)["data"].values()]
    without_secret = yaml.safe_dump_all([d for d in docs if d["kind"] != "Secret"])
    for value in secret_values:
        assert value not in without_secret
    assert "sk-" not in out
    values = yaml.safe_load((CHART / "values.yaml").read_text())

    def keys(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [k for k, v in node.items() for k in (k, *keys(v))]
        return []

    for key in keys(values):
        assert not re.search(r"password|secret|token|apikey", key, re.I), key


def test_api_and_worker_wait_for_postgres_and_temporal_before_starting() -> None:
    # Under make dev the file watcher does not restart a process that exits, so a start
    # before Postgres or Temporal listens would leave a dead process in a Running pod.
    docs = render()
    for name in ("api", "worker"):
        spec = _named(docs, "Deployment", name)["spec"]["template"]["spec"]
        (init,) = spec["initContainers"]
        assert init["image"] == _container(_named(docs, "Deployment", name))["image"]
        assert "postgres.ace.svc.cluster.local:5432" in init["command"], name
        assert "temporal.ace.svc.cluster.local:7233" in init["command"], name
