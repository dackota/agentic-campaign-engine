"""The brand reviewer: its AgentTemplate, its contract, and what it is sent."""

import uuid

import jsonschema
from ace_engine import db
from ace_engine.brand_review import (
    BRAND_REVIEWER,
    CHECKS,
    MAX_FIX_ROUNDS,
    fix_message,
    review_message,
    verdict_problems,
)
from ace_engine.contracts import REPORT_MARKER
from sqlalchemy.orm import Session

from tests.tooling.gateway_files import ROOT, yaml_docs

TEMPLATES = ROOT / "agents/templates.yaml"


def test_reviewer_has_a_template_whose_prompt_names_the_four_checks() -> None:
    templates = {d["metadata"]["name"]: d for d in yaml_docs(TEMPLATES)}

    assert templates[BRAND_REVIEWER.template]["spec"]["systemPrompt"] == BRAND_REVIEWER.prompt
    assert set(CHECKS) == {"uncited_fact", "banned_claim", "off_brand_word", "length"}
    for check in CHECKS:
        assert check in BRAND_REVIEWER.prompt
    jsonschema.Draft202012Validator.check_schema(BRAND_REVIEWER.schema)
    assert MAX_FIX_ROUNDS == 2


def test_review_message_carries_the_draft_the_report_and_the_research() -> None:
    text = review_message({"headline": "Patch now"}, {"research": {"facts": []}}, "line one")

    assert BRAND_REVIEWER.prompt in text
    assert "Patch now" in text and "OUTPUT OF research" in text
    assert text.endswith(f"{REPORT_MARKER}\nline one")


def test_fix_message_returns_the_issues_to_the_writer() -> None:
    issues = [{"check": "length", "detail": "body is too long"}]

    text = fix_message("You are the writer.", issues)

    assert text.startswith("You are the writer.")
    assert "length" in text and "body is too long" in text


def test_a_verdict_must_fit_the_contract() -> None:
    assert verdict_problems({"verdict": "pass", "issues": []}) == []
    assert verdict_problems({"verdict": "fix", "issues": []})
    assert verdict_problems({"verdict": "maybe", "issues": []})


def test_a_retried_step_shows_one_flag_the_latest() -> None:
    engine = db.make_engine("sqlite://")
    campaign_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        for reason in ('[{"check": "length", "detail": "old"}]', "[]"):
            db.add_agent_event(session, campaign_id, "social", db.FLAGGED, "s").reason = reason
        db.add_agent_event(session, campaign_id, "one_pager", db.FLAGGED, "s").reason = "[]"
    with Session(engine) as session:
        flags = db.review_flags(session, campaign_id)

    assert [(f.step, f.reason) for f in flags] == [("social", "[]"), ("one_pager", "[]")]
