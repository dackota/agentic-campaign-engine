"""The agent roles of the default workflow. Each has a contract (the shape of what it
returns), a system prompt, and an AgentTemplate of the same name in agents/templates.yaml
that runs it at live depth. At fast depth the scripted agent plays every role."""

from dataclasses import dataclass
from typing import Any

from ace_engine.contracts import (
    EMAIL_DRAFT_SCHEMA,
    LANDING_PAGE_SCHEMA,
    ONE_PAGER_SCHEMA,
    REPORT_MARKER,
    RESEARCH_SCHEMA,
    SOCIAL_POSTS_SCHEMA,
    STRATEGY_SCHEMA,
)

# The email writer returns the A/B test's two emails: variant A first.
EMAIL_VARIANTS = 2
VARIANT_B_INSTRUCTION = (
    "Write variant B of an A/B test: the same facts, a different subject line and angle."
)
_JSON_ONLY = "Reply with only JSON that has"


@dataclass(frozen=True)
class Role:
    step_id: str
    template: str
    prompt: str
    # The contract for the step's whole recorded output.
    schema: dict[str, Any]
    # The contract for one agent reply; differs from `schema` when the step asks the
    # agent more than once.
    reply_schema: dict[str, Any]
    # How many replies the step collects.
    replies: int = 1


def _role(step_id: str, template: str, prompt: str, schema: dict[str, Any]) -> Role:
    return Role(step_id, template, prompt, schema, schema)


EMAIL_ROLE = Role(
    step_id="email_writer",
    template="ace-email-writer",
    prompt=(
        "You are the email writer. Turn the threat report into a marketing email. "
        f"{_JSON_ONLY} the keys subject, preheader, body, call_to_action."
    ),
    schema={
        "type": "array",
        "minItems": EMAIL_VARIANTS,
        "maxItems": EMAIL_VARIANTS,
        "items": {k: v for k, v in EMAIL_DRAFT_SCHEMA.items() if k != "$schema"},
    },
    reply_schema=EMAIL_DRAFT_SCHEMA,
    replies=EMAIL_VARIANTS,
)

ROLES: dict[str, Role] = {
    r.step_id: r
    for r in (
        _role(
            "strategist",
            "ace-strategist",
            "You are the campaign strategist. Read the threat report and decide who to reach "
            f"and with what angle. {_JSON_ONLY} the keys audience, angle, key_messages "
            "(a list of strings).",
            STRATEGY_SCHEMA,
        ),
        _role(
            "research",
            "ace-research",
            "You are the research agent. Pull the facts out of the threat report. Number its "
            "lines from 1. Every fact must cite the line it comes from and quote that text "
            f"exactly. {_JSON_ONLY} the key facts: a list of objects with the keys claim, "
            "line, quote.",
            RESEARCH_SCHEMA,
        ),
        EMAIL_ROLE,
        _role(
            "landing_page",
            "ace-landing-page-writer",
            "You are the landing page writer. Turn the strategy and research into a landing "
            f"page. {_JSON_ONLY} the keys headline, subheadline, body, call_to_action.",
            LANDING_PAGE_SCHEMA,
        ),
        _role(
            "social",
            "ace-social-writer",
            "You are the social writer. Turn the strategy and research into social posts. "
            f"{_JSON_ONLY} the key posts: a list of objects with the keys channel, text.",
            SOCIAL_POSTS_SCHEMA,
        ),
        _role(
            "one_pager",
            "ace-one-pager-writer",
            "You are the one-pager writer. Turn the strategy and research into a one-page "
            f"brief. {_JSON_ONLY} the keys title, summary, bullets (a list of strings).",
            ONE_PAGER_SCHEMA,
        ),
    )
}


def role_for(step_id: str) -> Role:
    """The role of an agent step. A step in a saved workflow that is none of the default
    workflow's steps writes the email, as an agent step always has."""
    return ROLES.get(step_id, EMAIL_ROLE)


def message_for(role: Role, report: str, context: dict[str, Any], variant: int = 0) -> str:
    """What the agent is sent: the role's prompt, what earlier steps produced, then the
    report after the marker."""
    parts = [role.prompt]
    if variant > 0:
        parts.append(VARIANT_B_INSTRUCTION)
    for step_id, output in context.items():
        parts.append(f"OUTPUT OF {step_id}: {output}")
    return "\n\n".join(parts) + f"\n\n{REPORT_MARKER}\n{report}"
