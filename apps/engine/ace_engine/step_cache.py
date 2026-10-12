"""Step cache: a saved agent step result, reused when the same step runs again.

The key is the step type, the agent revision digest, and a hash of the input. The revision
digest is a hash of the agent's card, which the agent serves at
`<agent url>/.well-known/agent-card.json`, so a new revision of the agent misses. Entries
are kept per team: the cache reads and writes as its team (`row_security.for_team`), so
row-level security keeps one team from another's output. See docs/decisions/step-cache.md
and docs/decisions/team-isolation.md."""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ace_engine import db, row_security

logger = logging.getLogger(__name__)

CARD_PATH = "/.well-known/agent-card.json"
CARD_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class CacheKey:
    step_type: str
    agent_digest: str
    input_hash: str


@dataclass(frozen=True)
class CachedStep:
    output: Any
    model: str


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def input_hash(report: str, context: dict[str, Any], review_rounds: int) -> str:
    """The hash of everything the step is asked: the report, what earlier steps produced,
    and how many review rounds it gets. Key order does not matter."""
    return _digest({"report": report, "context": context, "review_rounds": review_rounds})


async def agent_revision(client: httpx.AsyncClient, agent_url: str) -> str | None:
    """The digest of the agent's card, or None when the card cannot be read: a step whose
    revision is unknown is never cached."""
    try:
        response = await client.get(agent_url.rstrip("/") + CARD_PATH, timeout=CARD_TIMEOUT_SECONDS)
        response.raise_for_status()
        return _digest(response.json())
    except (httpx.HTTPError, ValueError):
        logger.warning("agent card unreadable at %s; the step is not cached", agent_url)
        return None


class StepCache:
    def __init__(self, engine: Engine, team: str) -> None:
        self._engine = row_security.for_team(engine, team)
        self._team = team

    def get(self, key: CacheKey) -> CachedStep | None:
        with Session(self._engine) as session:
            row = session.scalars(select(db.StepCacheEntry).filter_by(**self._where(key))).first()
            return None if row is None else CachedStep(output=row.output, model=row.model)

    def put(self, key: CacheKey, output: Any, model: str) -> None:
        """Save the output. The first entry for a key stays: racing writers agree."""
        values = {**self._where(key), "output": output, "model": model}
        # The entry's owner, not a filter: the database checks it is the caller's team.
        values.update(team=self._team)
        dialect = self._engine.dialect.name
        insert = (postgresql.insert if dialect == "postgresql" else sqlite.insert)(
            db.StepCacheEntry
        )
        with Session(self._engine) as session, session.begin():
            session.execute(insert.values(**values).on_conflict_do_nothing())

    def _where(self, key: CacheKey) -> dict[str, str]:
        return {
            "step_type": key.step_type,
            "agent_digest": key.agent_digest,
            "input_hash": key.input_hash,
        }
