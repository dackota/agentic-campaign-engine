"""The golden set: made-up threat reports, each with the key facts a campaign must carry."""

import json
from dataclasses import dataclass
from pathlib import Path

GOLDEN_PATH = Path(__file__).with_name("golden.json")


@dataclass(frozen=True)
class GoldenReport:
    id: str
    report: str
    key_facts: tuple[str, ...]


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenReport]:
    """Read the golden set; a malformed entry fails loudly, with its position."""
    raw = json.loads(path.read_text())
    entries: list[GoldenReport] = []
    for position, item in enumerate(raw):
        try:
            entries.append(GoldenReport(item["id"], item["report"], tuple(item["key_facts"])))
        except (KeyError, TypeError) as error:
            raise ValueError(f"golden entry {position} is malformed: {error!r}") from error
    return entries
