"""The brand review loop. A writer step with `review_rounds` sends its draft to the brand
reviewer. On a fix verdict the issues go back to the same writer Session, for at most
MAX_FIX_ROUNDS rounds; what the reviewer still flags after that is left for a human."""

import json
from typing import Any

from ace_engine.agent_roles import Role
from ace_engine.contracts import REPORT_MARKER, AgentOutput, violations

MAX_FIX_ROUNDS = 2
PASS = "pass"
FIX = "fix"

CHECKS = ("uncited_fact", "banned_claim", "off_brand_word", "length")

VERDICT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["verdict", "issues"],
    "properties": {
        "verdict": {"enum": [PASS, FIX]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["check", "detail"],
                "properties": {"check": {"enum": list(CHECKS)}, "detail": {"type": "string"}},
            },
        },
    },
    "if": {"properties": {"verdict": {"const": FIX}}},
    "then": {"properties": {"issues": {"minItems": 1}}},
}

BRAND_REVIEWER = Role(
    step_id="brand_reviewer",
    template="ace-brand-reviewer",
    prompt=(
        "You are the brand reviewer. Check the draft against the threat report with four "
        "checks: uncited_fact (a fact that does not cite a line of the report), banned_claim "
        "(a guarantee or absolute claim such as 100% protection), off_brand_word (hype or "
        "fear words the brand never uses), and length (a headline, subject, or body that is "
        "too long). Reply with only JSON that has the keys verdict (pass or fix) and issues "
        "(a list of objects with the keys check and detail; empty when the verdict is pass)."
    ),
    schema=VERDICT_SCHEMA,
    reply_schema=VERDICT_SCHEMA,
)


def verdict_problems(verdict: object) -> list[str]:
    return violations(verdict, VERDICT_SCHEMA)


def review_message(draft: AgentOutput, context: dict[str, Any], report: str) -> str:
    """What the reviewer is sent: its prompt, the draft, what earlier steps produced, and
    the report after the marker."""
    parts = [BRAND_REVIEWER.prompt, f"DRAFT: {json.dumps(draft)}"]
    parts += [f"OUTPUT OF {step_id}: {output}" for step_id, output in context.items()]
    return "\n\n".join(parts) + f"\n\n{REPORT_MARKER}\n{report}"


def fix_message(writer_prompt: str, issues: list[dict[str, Any]]) -> str:
    """What the writer is sent in its own Session: the reviewer's issues, to fix in the
    same reply format."""
    listed = "\n".join(f"- {i['check']}: {i['detail']}" for i in issues)
    return (
        f"{writer_prompt}\n\nThe brand reviewer sent your draft back. Fix these issues and "
        f"reply with the whole corrected draft in the same format:\n{listed}"
    )
