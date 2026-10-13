"""How long each text field of a writer's reply may be, in characters. The eval's hard checks
grade against the same numbers (evals/checks.py keeps a copy so the evals run without the
engine; a test keeps the two equal). The writer is told them, since a model cannot keep to a
limit it never sees."""

from collections.abc import Iterator
from typing import Any

MAX_CHARS = {
    "subject": 100,
    "preheader": 150,
    "body": 2000,
    "call_to_action": 60,
    "headline": 120,
    "subheadline": 200,
    "title": 120,
    "summary": 600,
    "bullets": 300,
    "text": 280,
}


def _fields(schema: dict[str, Any]) -> Iterator[str]:
    """Every property name in `schema`, nested ones included, in schema order."""
    for name, sub in (schema.get("properties") or {}).items():
        yield name
        yield from _fields(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _fields(items)


def limits_line(schema: dict[str, Any]) -> str:
    """The sentence that tells a writer its length limits; empty when no field has one."""
    limited = [f"{f}: at most {MAX_CHARS[f]} characters" for f in _fields(schema) if f in MAX_CHARS]
    if not limited:
        return ""
    return "Keep within these lengths (for a list, each item): " + "; ".join(limited) + "."
