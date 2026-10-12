"""The sandbox design agent: its role, contract, live manifests, and the script that runs
its code in a standalone sandbox with the network shut."""

import json
from typing import Any

import jsonschema
import pytest
from ace_engine import contracts
from ace_engine.agent_roles import ROLES, role_for
from ace_engine.contracts import violations

from tests.harness.scripted_agent import default_reply
from tests.tooling.gateway_files import ROOT, yaml_docs

TEMPLATES = ROOT / "agents/templates.yaml"
AGENTS = ROOT / "agents/agents.yaml"
SCRIPT = ROOT / "scripts/design-sandbox.sh"
DECISION = ROOT / "docs/decisions/sandbox-design-agent.md"
SANDBOX_TEMPLATE = "ace-design-sandbox"
GOOD_CARD = {"name": "social-card-1.svg", "svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"}


def _cards(*cards: dict[str, str]) -> dict[str, Any]:
    return {"cards": list(cards)}


def test_design_role_has_a_contract_template_and_agent() -> None:
    role = role_for("design")
    templates = {d["metadata"]["name"]: d for d in yaml_docs(TEMPLATES)}
    agents = {d["metadata"]["name"]: d for d in yaml_docs(AGENTS)}

    assert role is ROLES["design"]
    jsonschema.Draft202012Validator.check_schema(role.schema)
    assert templates[role.template]["kind"] == "AgentTemplate"
    assert templates[role.template]["spec"]["systemPrompt"] == role.prompt
    assert agents[role.template]["spec"]["templateRef"]["name"] == role.template
    assert "sandbox" in role.prompt


def test_scripted_agent_plays_the_design_role() -> None:
    message = f"{ROLES['design'].prompt}\n\nTHREAT REPORT:\nVolt Typhoon"

    reply = default_reply(message)

    assert violations(reply, contracts.DESIGN_CARDS_SCHEMA) == []
    assert reply == default_reply(message + " and more")  # a fixed card pair


@pytest.mark.parametrize(
    "bad",
    [
        _cards(GOOD_CARD),
        _cards(GOOD_CARD, GOOD_CARD, GOOD_CARD),
        _cards(GOOD_CARD, {"name": "../escape.svg", "svg": "<svg/>"}),
        _cards(GOOD_CARD, {"name": "card.svg", "svg": "<svg><script>x()</script></svg>"}),
        _cards(GOOD_CARD, {"name": "card.svg", "svg": "<svg onload='x()'/>"}),
        _cards(GOOD_CARD, {"name": "card.svg", "svg": "not an image"}),
        {"cards": []},
        {},
    ],
)
def test_contract_wants_exactly_two_safe_cards(bad: dict[str, Any]) -> None:
    assert violations(bad, contracts.DESIGN_CARDS_SCHEMA)


def test_contract_accepts_two_svg_cards() -> None:
    second = {"name": "social-card-2.svg", "svg": "<svg/>"}

    assert violations(_cards(GOOD_CARD, second), contracts.DESIGN_CARDS_SCHEMA) == []


def test_sandbox_template_is_pinned_and_carries_no_env_or_secret() -> None:
    template = next(d for d in yaml_docs(TEMPLATES) if d["metadata"]["name"] == SANDBOX_TEMPLATE)

    assert template["kind"] == "SandboxTemplate"
    assert "@sha256:" in template["spec"]["workload"]["image"]
    assert "env" not in template["spec"]["workload"]
    assert "env" not in template["spec"]


def test_sandbox_script_runs_code_and_deletes_the_sandbox() -> None:
    script = SCRIPT.read_text()

    assert "sandbox create" in script and "sandbox exec" in script
    assert "sandbox delete" in script and "trap" in script
    assert SANDBOX_TEMPLATE in script
    assert 'KCTX="${KCTX:-k3d-ace}"' in script  # never the spike cluster


def test_sandbox_script_probes_a_host_the_sandbox_does_not_need() -> None:
    script = SCRIPT.read_text()

    assert "example.com" in script
    assert "NOT REACHABLE" in script


def test_decision_records_what_the_sandbox_may_reach() -> None:
    text = DECISION.read_text()

    assert "nothing" in text.lower()
    assert "spike-log" in text
    assert json.dumps(SANDBOX_TEMPLATE)[1:-1] in text
