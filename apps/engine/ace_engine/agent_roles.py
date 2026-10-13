"""The agent roles of the default workflow. Each has a contract (the shape of what it
returns), a system prompt, and an AgentTemplate of the same name in agents/templates.yaml
that runs it at live depth. At fast depth the scripted agent plays every role."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ace_engine.contracts import (
    DESIGN_CARDS_SCHEMA,
    DESIGN_REPLY_SCHEMA,
    EMAIL_DRAFT_SCHEMA,
    LANDING_PAGE_SCHEMA,
    ONE_PAGER_SCHEMA,
    REPORT_MARKER,
    RESEARCH_SCHEMA,
    SOCIAL_POSTS_SCHEMA,
    STRATEGY_SCHEMA,
)
from ace_engine.judge import JUDGE_STEP, SCORES_SCHEMA
from ace_engine.judge import PROMPT as JUDGE_PROMPT
from ace_engine.limits import limits_line
from ace_engine.settings import Depth

# The email writer returns the A/B test's two emails: variant A first.
EMAIL_VARIANTS = 2
VARIANT_B_INSTRUCTION = (
    "Write variant B of an A/B test: the same facts, a different subject line and angle."
)
_JSON_ONLY = "Reply with only JSON that has"
# The research and writer agents read what won before (the learnings search MCP tool).
LEARNINGS_FIRST = (
    "Before you write, call the search_learnings tool with what you are about to write "
    "about, and use the lines that won before where they fit."
)
DESIGN_PROMPT = (
    "You are the design agent. Turn the strategy and research into two social cards, each an "
    "SVG image of 1200 by 630 pixels. Write a shell script that draws them and prints, for "
    "each card n (1 or 2), one line: CARD n followed by a space and the base64 of the SVG on "
    "one line. The engine runs your script in a sandbox with no network and reads the cards "
    "from what it prints, so use no outside file, package or font and put no script in the "
    f"SVG. {_JSON_ONLY} the key program: your script as one string."
)
# A team's Agents live in the namespace `team-<team>`; the whole name is a DNS label.
TEAM_NAMESPACE_PREFIX = "team-"
TEAM_NAME = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,56}[a-z0-9])?")


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
    # Whether the output's facts must cite lines of the report.
    checks_citations: bool = False
    # Whether the output is the campaign's email draft and its A/B variant.
    writes_draft: bool = False
    # Whether the output is the two social cards the engine saves to the asset library.
    makes_cards: bool = False
    # Whether the output is the judge's scores, which the engine records and holds to the floor.
    judges: bool = False


def _role(
    step_id: str,
    template: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    checks_citations: bool = False,
) -> Role:
    return Role(step_id, template, prompt, schema, schema, checks_citations=checks_citations)


EMAIL_ROLE = Role(
    step_id="email_writer",
    template="ace-email-writer",
    prompt=(
        "You are the email writer. Turn the threat report into a marketing email. "
        f"{LEARNINGS_FIRST} {_JSON_ONLY} the keys subject, preheader, body, call_to_action."
    ),
    schema={
        "type": "array",
        "minItems": EMAIL_VARIANTS,
        "maxItems": EMAIL_VARIANTS,
        "items": {k: v for k, v in EMAIL_DRAFT_SCHEMA.items() if k != "$schema"},
    },
    reply_schema=EMAIL_DRAFT_SCHEMA,
    replies=EMAIL_VARIANTS,
    writes_draft=True,
)

ROLES: Mapping[str, Role] = MappingProxyType(
    {
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
                "You are the research agent. Pull the facts out of the threat report. Before you "
                "answer, look up the campaign's Workfront project with the get_project tool "
                "(search_projects finds it), for context only. "
                f"{LEARNINGS_FIRST} Number the report's lines from 1. "
                "Every fact must cite the line it comes from and quote that text "
                f"exactly. {_JSON_ONLY} the key facts: a list of objects with the keys claim, "
                "line, quote.",
                RESEARCH_SCHEMA,
                checks_citations=True,
            ),
            EMAIL_ROLE,
            _role(
                "landing_page",
                "ace-landing-page-writer",
                "You are the landing page writer. Turn the strategy and research into a landing "
                f"page. {LEARNINGS_FIRST} {_JSON_ONLY} the keys headline, subheadline, body, "
                "call_to_action.",
                LANDING_PAGE_SCHEMA,
            ),
            _role(
                "social",
                "ace-social-writer",
                "You are the social writer. Turn the strategy and research into social posts. "
                f"{LEARNINGS_FIRST} {_JSON_ONLY} the key posts: a list of objects with the keys "
                "channel, text.",
                SOCIAL_POSTS_SCHEMA,
            ),
            _role(
                "one_pager",
                "ace-one-pager-writer",
                "You are the one-pager writer. Turn the strategy and research into a one-page "
                f"brief. {LEARNINGS_FIRST} {_JSON_ONLY} the keys title, summary, bullets (a list "
                "of strings).",
                ONE_PAGER_SCHEMA,
            ),
            Role(
                step_id=JUDGE_STEP,
                template="ace-judge",
                prompt=JUDGE_PROMPT,
                schema=SCORES_SCHEMA,
                reply_schema=SCORES_SCHEMA,
                judges=True,
            ),
            Role(
                step_id="design",
                template="ace-design-agent",
                prompt=DESIGN_PROMPT,
                schema=DESIGN_CARDS_SCHEMA,
                reply_schema=DESIGN_REPLY_SCHEMA,
                makes_cards=True,
            ),
        )
    }
)


def role_for(step_id: str) -> Role:
    """The role of an agent step. A step in a saved workflow that is none of the default
    workflow's steps writes the email, as an agent step always has."""
    return ROLES.get(step_id, EMAIL_ROLE)


def message_for(role: Role, report: str, context: dict[str, Any], variant: int = 0) -> str:
    """What the agent is sent: the role's prompt, what earlier steps produced, then the
    report after the marker."""
    parts = [role.prompt]
    limits = limits_line(role.reply_schema)
    if limits:
        parts.append(limits)
    if variant > 0:
        parts.append(VARIANT_B_INSTRUCTION)
    for step_id, output in context.items():
        parts.append(f"OUTPUT OF {step_id}: {output}")
    return "\n\n".join(parts) + f"\n\n{REPORT_MARKER}\n{report}"


def team_namespace(team: str) -> str:
    """The Kubernetes namespace of a team's Agents: `team-<team>`. A team that would not
    make a namespace name is refused, so it can never point a URL at another namespace."""
    if not TEAM_NAME.fullmatch(team):
        raise ValueError(f"team {team!r} is not a namespace name (lowercase letters, digits, -)")
    return f"{TEAM_NAMESPACE_PREFIX}{team}"


def agent_url_for(base_url: str, depth: Depth, role: Role, team: str | None = None) -> str:
    """Where to send a role's messages. At live depth each role is its own kagent Agent,
    named like its template, under the controller's base URL
    (`<controller>/agents/<namespace>`); with `team` the Agent is the one in the team's own
    namespace. At fast depth the scripted agent plays every role at the one URL."""
    if depth is not Depth.LIVE:
        return base_url
    base = base_url.rstrip("/")
    if team is not None:
        base = f"{base.rsplit('/', 1)[0]}/{team_namespace(team)}"
    return f"{base}/{role.template}"
