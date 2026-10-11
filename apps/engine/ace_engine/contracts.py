"""Output contracts. One JSON Schema file per output type is the source of truth."""

import json
from pathlib import Path
from typing import Any

import jsonschema

_DIR = Path(__file__).parent
# The worker's prompt for every role puts the threat report after this marker; the
# scripted agent reads it back out from there.
REPORT_MARKER = "THREAT REPORT:"


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((_DIR / name).read_text())
    return loaded


def _contract(name: str) -> dict[str, Any]:
    return _load(f"{name}.schema.json")


EMAIL_DRAFT_SCHEMA = _load("email_draft.schema.json")
STRATEGY_SCHEMA = _contract("strategy")
RESEARCH_SCHEMA = _contract("research")
LANDING_PAGE_SCHEMA = _contract("landing_page")
SOCIAL_POSTS_SCHEMA = _contract("social_posts")
ONE_PAGER_SCHEMA = _contract("one_pager")


def violations(instance: object, schema: dict[str, Any]) -> list[str]:
    """Plain-language list of the ways `instance` breaks `schema`; empty when valid."""
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or 'reply'}: {e.message}"
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


def citation_problems(research: dict[str, Any], report: str) -> list[str]:
    """Facts whose cited line is not in the report, or whose quote is not on that line."""
    lines = report.splitlines()
    problems = []
    for fact in research.get("facts", []):
        line = fact.get("line")
        quote = fact.get("quote", "")
        if not isinstance(line, int) or not 1 <= line <= len(lines):
            problems.append(
                f"fact {fact.get('claim')!r} cites line {line}, which is not in the report"
            )
        elif not quote.strip() or quote not in lines[line - 1]:
            problems.append(f"fact {fact.get('claim')!r} quotes text that is not on line {line}")
    return problems
