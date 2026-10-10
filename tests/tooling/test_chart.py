"""The one chart for our services: rendered with `helm template`, offline."""

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/ace"
CLUSTER_CONFIG = ROOT / "platform/ace-cluster.yaml"
OUR_IMAGE_REPOS = ("ace-web", "ace-python")


def render(*sets: str) -> list[dict[str, Any]]:
    args = ["helm", "template", "ace", str(CHART), "--namespace", "ace"]
    for value in sets:
        args += ["--set", value]
    out = _helm(args)
    return [d for d in yaml.safe_load_all(out) if d]


def by_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [d for d in docs if d["kind"] == kind]


def web_objects(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [d for d in by_kind(docs, kind) if d["metadata"]["name"] == "web"]


def test_chart_renders_web_deployment_and_nodeport_service() -> None:
    docs = render()
    (deploy,) = web_objects(docs, "Deployment")
    (svc,) = web_objects(docs, "Service")
    assert deploy["metadata"]["name"] == "web"
    assert svc["spec"]["type"] == "NodePort"
    assert svc["spec"]["selector"].items() <= (
        deploy["spec"]["template"]["metadata"]["labels"].items()
    )
    container = deploy["spec"]["template"]["spec"]["containers"][0]
    port = container["ports"][0]["containerPort"]
    assert svc["spec"]["ports"][0]["targetPort"] in (port, container["ports"][0]["name"])


def test_nodeport_matches_cluster_config_mapping() -> None:
    mapped = yaml.safe_load(CLUSTER_CONFIG.read_text())["ports"]
    web = [p["port"] for p in mapped if p["port"].startswith("15180:")]
    assert web == ["15180:30180"]
    (svc,) = web_objects(render(), "Service")
    assert svc["spec"]["ports"][0]["nodePort"] == 30180


def test_web_image_comes_from_values() -> None:
    (deploy,) = web_objects(render("web.image.repository=reg/x", "web.image.tag=t1"), "Deployment")
    image = deploy["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == "reg/x:t1"


def test_api_service_name_comes_from_values() -> None:
    (deploy,) = web_objects(render("api.serviceName=my-api", "api.port=9000"), "Deployment")
    env = {
        e["name"]: e.get("value")
        for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    # nginx's resolver ignores search domains, so the name must be fully qualified.
    assert env["API_HOST"] == "my-api.ace.svc.cluster.local"
    assert env["API_PORT"] == "9000"
    assert env["DNS_RESOLVER"]


def test_every_image_is_ours_or_pinned_by_digest() -> None:
    images = re.findall(r"^\s*image:\s*\"?([^\s\"]+)", _raw_render(), re.M)
    assert images
    for image in images:
        name = image.rsplit("/", 1)[-1].split("@")[0].split(":")[0]
        ours = name in OUR_IMAGE_REPOS
        assert ours or re.search(r"@sha256:[0-9a-f]{64}$", image), image


def _raw_render() -> str:
    return _helm(["helm", "template", "ace", str(CHART), "--namespace", "ace"])


def _helm(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout
