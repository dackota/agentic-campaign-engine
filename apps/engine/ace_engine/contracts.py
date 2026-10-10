"""Output contracts. One JSON Schema file per output type is the source of truth."""

import json
from pathlib import Path
from typing import Any

import jsonschema

_DIR = Path(__file__).parent
# The worker's email prompt puts the threat report after this marker; the scripted agent
# reads it back out from there.
REPORT_MARKER = "THREAT REPORT:"


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((_DIR / name).read_text())
    return loaded


EMAIL_DRAFT_SCHEMA = _load("email_draft.schema.json")


def violations(instance: object, schema: dict[str, Any]) -> list[str]:
    """Plain-language list of the ways `instance` breaks `schema`; empty when valid."""
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or 'reply'}: {e.message}"
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]
