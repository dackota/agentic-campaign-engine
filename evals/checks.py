"""The hard checks: deterministic content checks run on every asset. They mirror the brand
reviewer's four checks, but need no model, so the same asset always gets the same verdict."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

CHECK_NAMES = ("uncited_fact", "banned_claim", "off_brand_word", "length")

BANNED_CLAIMS = re.compile(
    r"100\s?%|guarantee|completely (?:eliminat|prevent|protect|secure)|unbreakable|"
    r"impossible to (?:breach|hack)|never (?:fail|be breached)",
    re.IGNORECASE,
)
OFF_BRAND_WORDS = re.compile(
    r"\b(?:terrifying|catastrophic|devastating|panic|unstoppable|game[- ]changing|"
    r"revolutionary|nightmare|doomsday|skyrocket\w*)\b",
    re.IGNORECASE,
)
# The longest each text field may be, in characters.
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


@dataclass(frozen=True)
class CheckResult:
    check: str
    passed: bool
    detail: str = ""


def fields(output: object, name: str = "") -> Iterator[tuple[str, str]]:
    """Every (field name, text) in an asset's output, whatever its nesting."""
    if isinstance(output, str):
        yield name, output
    elif isinstance(output, dict):
        for key, value in output.items():
            yield from fields(value, key)
    elif isinstance(output, list):
        for item in output:
            yield from fields(item, name)


def texts(output: object) -> list[str]:
    return [text for _, text in fields(output)]


def _scan(check: str, pattern: re.Pattern[str], output: object) -> CheckResult:
    hits = sorted({m.group(0).lower() for text in texts(output) for m in pattern.finditer(text)})
    return CheckResult(check, not hits, f"found {', '.join(repr(h) for h in hits)}" if hits else "")


def _length(output: object) -> CheckResult:
    over = [
        f"{name} is {len(text)} characters (limit {MAX_CHARS[name]})"
        for name, text in fields(output)
        if name in MAX_CHARS and len(text) > MAX_CHARS[name]
    ]
    return CheckResult("length", not over, "; ".join(over))


def _squash(text: str) -> str:
    return " ".join(text.split())


def _uncited(step: str, output: object, report: str) -> CheckResult:
    """Research facts must quote the report line they cite. Other assets cite nothing."""
    if step != "research":
        return CheckResult("uncited_fact", True)
    lines = report.splitlines()
    bad = []
    for fact in output.get("facts", []) if isinstance(output, dict) else []:
        line, quote = fact.get("line"), _squash(str(fact.get("quote", "")))
        cited = _squash(lines[line - 1]) if isinstance(line, int) and 0 < line <= len(lines) else ""
        if not quote or quote not in cited:
            bad.append(f"line {line}: {quote[:60]!r} is not on that line")
    return CheckResult("uncited_fact", not bad, "; ".join(bad))


def check_asset(step: str, output: object, report: str) -> list[CheckResult]:
    """Run every hard check on one asset's recorded output."""
    return [
        _uncited(step, output, report),
        _scan("banned_claim", BANNED_CLAIMS, output),
        _scan("off_brand_word", OFF_BRAND_WORDS, output),
        _length(output),
    ]
