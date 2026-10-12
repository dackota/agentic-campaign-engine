"""Checks on what an agent hands a tool, before any of it reaches an upstream path."""

import re
from typing import Any

_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")
_DOT_SEGMENTS = (".", "..")


def segment(args: dict[str, Any], name: str) -> str:
    """A required argument that must be one path segment: an ID or a slug.

    Anything with a `/`, `.`, `?` or `#` could leave the route it is put in, so it is refused.
    """
    value = str(args[name])
    if not _SEGMENT.fullmatch(value):
        raise ValueError(f"{name} must be a single id of letters, digits, '_' or '-'")
    return value


def optional_segment(args: dict[str, Any], name: str) -> str:
    """Like `segment`, for a filter that may be left out (an empty value is no filter)."""
    return segment(args, name) if args.get(name) else ""


def key_path(args: dict[str, Any], name: str) -> str:
    """A required object key: slashes are fine, `.` and `..` segments are not."""
    value = str(args[name])
    if not value or any(part in _DOT_SEGMENTS for part in value.split("/")):
        raise ValueError(f"{name} must not contain '.' or '..' segments")
    return value
