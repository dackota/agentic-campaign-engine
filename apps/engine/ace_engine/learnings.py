"""The learnings store: a called A/B winner kept as a learning, and a search over a team's
learnings by meaning (docs/decisions/learnings-store.md).

Every function here takes the engine its caller should use. The API and the learnings MCP
server pass `row_security.for_team(...)`, so the database shows them one team's learnings;
the webhook that records a winner acts for the system and passes the owner engine.
"""

import hashlib
import math
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import cast, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ace_engine import db
from ace_engine.settings import Depth

Embed = Callable[[str], list[float]]
SEARCH_LIMIT = 5
MAX_QUERY_CHARS = 2_000
_WORD = re.compile(r"[a-z0-9]+")
# The stand-in's vector for text with no words: any fixed unit vector will do.
_BLANK_INDEX = 0


def stand_in_embedding(text: str) -> list[float]:
    """The fixed stand-in for an embedding model at fast depth: each lower-cased word is
    hashed to one of the vector's positions and counted, then the vector is scaled to unit
    length. The same text always gives the same vector, and texts that share words are
    closer than texts that share none, so a search still finds its match."""
    counts = [0.0] * db.EMBEDDING_DIMENSIONS
    for word in _WORD.findall(text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        counts[int.from_bytes(digest[:4], "big") % db.EMBEDDING_DIMENSIONS] += 1.0
    norm = math.sqrt(math.fsum(x * x for x in counts))
    if norm == 0.0:
        counts[_BLANK_INDEX] = 1.0
        return counts
    return [x / norm for x in counts]


def _embedding_of(response: httpx.Response) -> list[float]:
    """The first embedding of an OpenAI-shaped reply, or a ValueError naming the gateway."""
    try:
        data = response.json().get("data")
        embedding = data[0]["embedding"] if isinstance(data, list) and data else None
    except (ValueError, AttributeError, KeyError, TypeError):
        embedding = None
    if not isinstance(embedding, list) or not all(
        isinstance(x, int | float) and not isinstance(x, bool) for x in embedding
    ):
        raise ValueError("the gateway's embedding reply has no list of numbers at data[0]")
    return [float(x) for x in embedding]


class GatewayEmbedder:
    """Embeddings from the model gateway's OpenAI-shaped `/embeddings` route. The gateway
    holds the provider key, so this sends none."""

    def __init__(self, client: httpx.Client, url: str, model: str) -> None:
        self._client = client
        self._url = f"{url.rstrip('/')}/embeddings"
        self._model = model

    def __call__(self, text: str) -> list[float]:
        response = self._client.post(
            self._url,
            json={"model": self._model, "input": text, "dimensions": db.EMBEDDING_DIMENSIONS},
        )
        response.raise_for_status()
        vector = _embedding_of(response)
        if len(vector) != db.EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"the gateway returned {len(vector)} numbers, not {db.EMBEDDING_DIMENSIONS}"
            )
        return vector


# How long the owner's HTTP client waits for the gateway's embedding.
EMBED_TIMEOUT_SECONDS = 30.0


def embedder_for(depth: Depth, url: str, model: str, client: httpx.Client) -> Embed:
    """The stand-in at fast depth or when no gateway is set; the gateway otherwise, over
    `client`, which the caller owns and closes."""
    if depth is Depth.FAST or not url.strip() or not model.strip():
        return stand_in_embedding
    return GatewayEmbedder(client, url, model)


@dataclass(frozen=True)
class Winner:
    """A called A/B result and the engagement it was called on."""

    variant: str
    confidence: float
    engagement: Mapping[str, Mapping[str, int]]


def _winning_lines(campaign: db.Campaign, variant: str) -> str | None:
    email = campaign.draft if variant == "A" else campaign.variant_b
    if not email:
        return None
    lines = (email.get(k) for k in ("subject", "preheader", "call_to_action"))
    return "\n".join(str(line) for line in lines if line)


def _reason(winner: Winner) -> str:
    opens = {v: winner.engagement[v]["opens"] for v in sorted(winner.engagement)}
    counts = " against ".join(f"{n} opens for {v}" for v, n in opens.items())
    return f"Variant {winner.variant} won on opens ({counts}), {winner.confidence:.0%} confident."


def learn_from_winner(engine: Engine, campaign_id: uuid.UUID, winner: Winner, embed: Embed) -> bool:
    """Keep the campaign's winning lines as its one learning. False when the campaign has a
    learning already (a deleted one too), or has no winning email to learn from."""
    with Session(engine) as session:
        if session.scalar(select(db.Learning.id).where(db.Learning.campaign_id == campaign_id)):
            return False
        campaign = session.get(db.Campaign, campaign_id)
        lines = None if campaign is None else _winning_lines(campaign, winner.variant)
        if lines is None:
            return False
        metrics: dict[str, Any] = {
            "winner": winner.variant,
            "confidence": winner.confidence,
            "engagement": {v: dict(c) for v, c in winner.engagement.items()},
        }
        session.add(
            db.Learning(
                campaign_id=campaign_id,
                text=lines,
                reason=_reason(winner),
                metrics=metrics,
                embedding=embed(lines),
            )
        )
        try:
            session.commit()
        except IntegrityError:  # another webhook of the same campaign got there first
            session.rollback()
            return False
        return True


@dataclass(frozen=True)
class Found:
    learning: db.Learning
    campaign_title: str


def _title(report: str) -> str:
    return report.split("\n", 1)[0]


def list_learnings(engine: Engine) -> list[Found]:
    """Every learning the engine can see, newest first, with its source campaign's title."""
    with Session(engine, expire_on_commit=False) as session:
        rows = session.execute(
            select(db.Learning, db.Campaign.report)
            .join(db.Campaign, db.Campaign.id == db.Learning.campaign_id)
            .where(db.Learning.deleted_at.is_(None))
            .order_by(db.Learning.created_at.desc())
        )
        return [Found(learning, _title(report)) for learning, report in rows]


def search(engine: Engine, query: str, embed: Embed, limit: int = SEARCH_LIMIT) -> list[Found]:
    """The learnings nearest in meaning to `query` (cosine distance in pgvector), the
    newest first among equals."""
    wanted = embed(query[:MAX_QUERY_CHARS])
    distance = db.Learning.embedding.op("<=>")(cast(wanted, db.Embedding()))
    with Session(engine, expire_on_commit=False) as session:
        rows = session.execute(
            select(db.Learning, db.Campaign.report)
            .join(db.Campaign, db.Campaign.id == db.Learning.campaign_id)
            .where(db.Learning.deleted_at.is_(None))
            # Among equally near learnings, the newest first.
            .order_by(distance, db.Learning.created_at.desc())
            .limit(limit)
        )
        return [Found(learning, _title(report)) for learning, report in rows]


def remove(engine: Engine, learning_id: uuid.UUID) -> bool:
    """Delete one learning from the view and the search; False when the engine cannot see
    it. The row is kept, marked deleted, so the campaign never learns it again."""
    with Session(engine) as session, session.begin():
        result = session.execute(
            update(db.Learning)
            .where(db.Learning.id == learning_id, db.Learning.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
        return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]
