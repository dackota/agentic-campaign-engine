"""Row-level security is the only team filter: no query in the API names a team."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_code_adds_no_team_condition() -> None:
    """The campaign queries name no team: row-level security is the only team filter."""
    team_condition = re.compile(
        r"\.team\s*(==|!=)|\bteam\s*=\s*:|Campaign\.team\b|StepCacheEntry\.team\b|[\"']team[\"']\s*:"
    )
    sources = [
        *(ROOT / "apps/api/campaign_api").glob("*.py"),
        ROOT / "apps/engine/ace_engine/db.py",
        ROOT / "apps/engine/ace_engine/step_cache.py",
    ]

    found = [
        f"{path.name}:{n}: {line.strip()}"
        for path in sources
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if team_condition.search(line)
    ]

    assert found == []
