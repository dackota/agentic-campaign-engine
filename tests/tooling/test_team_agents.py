"""S6 live depth, checked offline: each team in Dex has its own namespace with every role
Agent of the default workflow, on its own ModelConfig, whose calls go through the team's
own gateway route and token limit. `platform/install.sh` applies every team."""

import re
import shutil
import subprocess
from typing import Any

import pytest
import yaml
from ace_engine.agent_roles import ROLES

from tests.harness.dex import DEMO_USERS
from tests.tooling.chart_files import CHART, by_kind, render
from tests.tooling.gateway_files import ROOT, yaml_docs

TEAMS_DIR = ROOT / "agents/teams"
TEAM_GATEWAY = TEAMS_DIR / "gateway.yaml"
GATEWAY_URL = "http://agentgateway-proxy.agentgateway-system.svc.cluster.local"
TEAMS = sorted({user.team for user in DEMO_USERS.values()})
LIVE_CAMPAIGN_PEAK_TOKENS_PER_MINUTE = 80_000


def _overlay(team: str) -> dict[str, Any]:
    (doc,) = yaml_docs(TEAMS_DIR / team / "kustomization.yaml")
    return doc


def _team_docs(team: str) -> list[dict[str, Any]]:
    return yaml_docs(TEAMS_DIR / team / "team.yaml")


def _named(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)


def test_the_demo_users_are_in_two_teams() -> None:
    assert TEAMS == ["demand-gen", "product-marketing"]


@pytest.mark.parametrize("team", TEAMS)
def test_every_team_has_every_role_agent_in_its_own_namespace_on_its_model(team: str) -> None:
    overlay = _overlay(team)
    docs = _team_docs(team)
    agents = {d["metadata"]["name"] for d in yaml_docs(ROOT / "agents/agents.yaml")}

    assert overlay["namespace"] == f"team-{team}"
    # kustomize refuses a base directory that holds the overlay, so the role files are named.
    assert {"../../templates.yaml", "../../agents.yaml", "../shared", "team.yaml"} == set(
        overlay["resources"]
    )
    assert {role.template for role in ROLES.values()} <= agents
    assert _named(docs, "Namespace", f"team-{team}")
    model = _named(docs, "ModelConfig", f"{team}-model")
    assert model["spec"]["openAI"]["baseUrl"] == f"{GATEWAY_URL}/{team}/v1"
    patches = {p["target"]["kind"]: p for p in overlay["patches"]}
    patch = patches["AgentTemplate"]
    assert f"value: {team}-model" in patch["patch"]
    assert "path: /spec/modelConfig/name" in patch["patch"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="needs kubectl's kustomize")
@pytest.mark.parametrize("team", TEAMS)
def test_every_team_overlay_builds_into_the_teams_namespace(team: str) -> None:
    built = subprocess.run(
        ["kubectl", "kustomize", "--load-restrictor", "LoadRestrictionsNone", TEAMS_DIR / team],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    docs = [d for d in yaml.safe_load_all(built) if d]

    namespaced = [d for d in docs if d["kind"] != "Namespace"]
    assert {d["metadata"]["namespace"] for d in namespaced} == {f"team-{team}"}
    agents = {d["metadata"]["name"] for d in docs if d["kind"] == "Agent"}
    assert {role.template for role in ROLES.values()} <= agents
    models = {d["spec"]["modelConfig"]["name"] for d in docs if d["kind"] == "AgentTemplate"}
    assert models == {f"{team}-model"}
    # kagent resolves a template's MCP server in the template's own namespace; a server
    # that is only in kagent leaves the team's Agent at ResolvedRefs=False forever.
    servers = {d["metadata"]["name"] for d in docs if d["kind"] == "RemoteMCPServer"}
    named = {
        tool["mcp"]["server"]["name"]
        for d in docs
        if d["kind"] == "AgentTemplate"
        for tool in d["spec"].get("tools", [])
    }
    assert named and named <= servers


@pytest.mark.parametrize("team", TEAMS)
def test_every_team_searches_only_its_own_learnings(team: str) -> None:
    """The learnings search server reads under one team's row-level security, so each
    team's copy of the RemoteMCPServer points at that team's own server."""
    patches = {p["target"]["kind"]: p for p in _overlay(team)["patches"]}

    patch = patches["RemoteMCPServer"]
    assert patch["target"]["name"] == "ace-mcp-learnings"
    assert "path: /spec/url" in patch["patch"]
    assert (
        f"value: http://ace-mcp-learnings-{team}.ace.svc.cluster.local:8000/mcp" in patch["patch"]
    )
    # ...and the chart runs that server, so the team's Agents resolve it.
    docs = render()
    server = f"ace-mcp-learnings-{team}"
    assert server in {d["metadata"]["name"] for d in by_kind(docs, "Deployment")}
    assert server in {d["metadata"]["name"] for d in by_kind(docs, "Service")}
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert team in values["learnings"]["teams"]


def test_the_shared_team_parts_match_the_kagent_namespace() -> None:
    shared = yaml_docs(TEAMS_DIR / "shared/runtime.yaml")
    spike_harness = _named(
        yaml_docs(ROOT / "manifests/spike/agent.yaml"), "Harness", "spike-harness"
    )
    install = (ROOT / "platform/install.sh").read_text()
    worker_image = re.search(r'^WORKER_IMAGE="([^"]+)"', install, re.MULTILINE)

    harness = _named(shared, "Harness", "spike-harness")
    pool = _named(shared, "WorkerPool", harness["spec"]["substrate"]["workerPoolRef"]["name"])
    assert harness["spec"]["workload"] == spike_harness["spec"]["workload"]
    # kagent picks a harness's workers by this label on the pool, not by the pool's name:
    # without it the Agent waits for its golden snapshot forever (ActorTemplatePending).
    assert pool["metadata"]["labels"]["kagent.dev/worker-pool"] == pool["metadata"]["name"]
    assert worker_image and pool["spec"]["workerImage"] == worker_image.group(1)
    secret = _named(shared, "Secret", "kagent-openai")
    # A placeholder the gateway ignores: the real key lives only in the gateway.
    assert set(secret["stringData"]) == {"OPENAI_API_KEY"}
    assert not secret["stringData"]["OPENAI_API_KEY"].startswith("sk-")


@pytest.mark.parametrize("team", TEAMS)
def test_every_team_model_goes_through_its_own_token_limited_route(team: str) -> None:
    docs = yaml_docs(TEAM_GATEWAY)

    route = _named(docs, "HTTPRoute", team)
    rule = route["spec"]["rules"][0]
    assert route["metadata"]["namespace"] == "agentgateway-system"
    assert rule["matches"][0]["path"]["value"] == f"/{team}/v1"
    assert rule["backendRefs"][0]["name"] == "opencode-go"
    sets = {h["name"]: h["value"] for h in rule["filters"][0]["requestHeaderModifier"]["set"]}
    assert sets["x-team"] == team
    limits = [
        p["spec"]["traffic"]["rateLimit"]["local"]
        for p in docs
        if p["kind"] == "AgentgatewayPolicy"
        and {"group": "gateway.networking.k8s.io", "kind": "HTTPRoute", "name": team}
        in p["spec"]["targetRefs"]
        and "rateLimit" in p["spec"].get("traffic", {})
    ]
    assert len(limits) == 1
    assert limits[0][0]["unit"] == "Minutes"
    # One live campaign peaked near 80k tokens a minute, throttled, on k3d-ace (2026-10-12);
    # the limit leaves room for two at once.
    assert limits[0][0]["tokens"] >= 2 * LIVE_CAMPAIGN_PEAK_TOKENS_PER_MINUTE


def test_install_applies_every_team_and_waits_for_its_agents() -> None:
    install = (ROOT / "platform/install.sh").read_text()
    status = (ROOT / "platform/status.sh").read_text()

    assert "agents/teams/gateway.yaml" in install
    assert "agents/teams/$team" in install
    assert "team-$team" in install
    for team in TEAMS:
        assert team in install
        assert f"team-{team}" in status or "team-$team" in status


@pytest.mark.parametrize("team", TEAMS)
def test_every_team_namespace_may_fetch_its_own_model_credentials(team: str) -> None:
    # Substrate's credential provider hands the model key only to an atespace it lists;
    # an unlisted team's Agent gets a 403 on every model call.
    (values,) = yaml_docs(ROOT / "manifests/spike/substrate-values.yaml")
    policies = values["credentialProvider"]["namespacePolicies"]

    assert {"atespace": f"team-{team}", "allowedNamespaces": [f"team-{team}"]} in policies
