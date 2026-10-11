"""The agent roles of the default workflow: a contract for each, an AgentTemplate for
live depth, and the citation rule for research output."""

import jsonschema
from ace_engine.agent_roles import EMAIL_ROLE, ROLES, role_for
from ace_engine.contracts import citation_problems

from tests.tooling.gateway_files import ROOT, yaml_docs

TEMPLATES = ROOT / "agents/templates.yaml"
EXPECTED_STEPS = {"strategist", "research", "email_writer", "landing_page", "social", "one_pager"}


def test_every_role_has_a_contract_and_an_agent_template() -> None:
    templates = {d["metadata"]["name"]: d for d in yaml_docs(TEMPLATES)}

    assert set(ROLES) == EXPECTED_STEPS
    for role in ROLES.values():
        jsonschema.Draft202012Validator.check_schema(role.schema)
        template = templates[role.template]
        assert template["kind"] == "AgentTemplate"
        assert template["spec"]["systemPrompt"] == role.prompt


def test_an_unknown_step_id_writes_email() -> None:
    assert role_for("draft") is EMAIL_ROLE
    assert role_for("writer_a") is EMAIL_ROLE


def test_citation_check_rejects_facts_not_in_the_report() -> None:
    report = "line one\nline two"
    good = {"facts": [{"claim": "c", "line": 2, "quote": "line two"}]}
    wrong_line = {"facts": [{"claim": "c", "line": 1, "quote": "line two"}]}
    out_of_range = {"facts": [{"claim": "c", "line": 3, "quote": "line two"}]}
    invented = {"facts": [{"claim": "c", "line": 1, "quote": "not there"}]}

    assert citation_problems(good, report) == []
    for bad in (wrong_line, out_of_range, invented):
        assert citation_problems(bad, report)
