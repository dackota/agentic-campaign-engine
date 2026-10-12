"""Live depth: every role of the default workflow is a real kagent Agent on the Go harness,
and its AgentTemplate calls the model through the gateway."""

from typing import Any

from ace_engine.agent_roles import ROLES
from ace_engine.brand_review import BRAND_REVIEWER

from tests.tooling.gateway_files import ROOT, yaml_docs

AGENTS = ROOT / "agents/agents.yaml"
TEMPLATES = ROOT / "agents/templates.yaml"
GATEWAY_MODEL = "gateway-model"
HARNESS = "spike-harness"


def _kind(docs: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == kind}


def test_every_role_has_an_agent_on_the_go_harness_and_gateway_model() -> None:
    templates = _kind(yaml_docs(TEMPLATES), "AgentTemplate")
    agents = _kind(yaml_docs(AGENTS), "Agent")
    harness = next(
        d
        for d in yaml_docs(ROOT / "manifests/spike/agent.yaml")
        if d["kind"] == "Harness" and d["metadata"]["name"] == HARNESS
    )

    assert "golang-adk" in harness["spec"]["workload"]["image"]
    for role in ROLES.values():
        assert templates[role.template]["spec"]["modelConfig"]["name"] == GATEWAY_MODEL
        agent = agents[role.template]
        assert agent["spec"]["templateRef"]["name"] == role.template
        assert agent["spec"]["harnessRef"]["name"] == HARNESS
        assert agent["metadata"]["namespace"] == "kagent"


def test_install_applies_the_agents_and_waits_for_the_email_writer() -> None:
    install = (ROOT / "platform/install.sh").read_text()
    status = (ROOT / "platform/status.sh").read_text()

    assert "agents/templates.yaml" in install and "agents/agents.yaml" in install
    assert "agent/ace-email-writer" in install
    assert "ace-email-writer" in status


def test_chart_points_the_worker_at_the_kagent_controller_at_live_depth() -> None:
    values = (ROOT / "charts/ace/values.yaml").read_text()

    assert "depth: live" in values
    assert "kagent-controller.kagent.svc.cluster.local:8083/agents/kagent" in values


def test_brand_reviewer_has_an_agent_on_the_go_harness() -> None:
    agents = _kind(yaml_docs(AGENTS), "Agent")

    agent = agents[BRAND_REVIEWER.template]

    assert agent["spec"]["templateRef"]["name"] == BRAND_REVIEWER.template
    assert agent["spec"]["harnessRef"]["name"] == HARNESS
    assert agent["metadata"]["namespace"] == "kagent"


def test_brand_reviewer_template_uses_gateway_model() -> None:
    templates = _kind(yaml_docs(TEMPLATES), "AgentTemplate")

    assert templates[BRAND_REVIEWER.template]["spec"]["modelConfig"]["name"] == GATEWAY_MODEL


def test_docs_name_no_mock_model_exception() -> None:
    for path in (TEMPLATES, ROOT / "agents/README.md"):
        assert "mock-model" not in path.read_text(), path
