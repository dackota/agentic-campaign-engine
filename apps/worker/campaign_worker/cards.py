"""Social cards: the engine, not the design agent, saves them to the asset library.

A card is stored under `cards/<campaign>/<name>` in the asset bucket, so the write is
idempotent by key: a retried step replaces a card with itself and never adds a second."""

from typing import Any

import httpx
from ace_engine.settings import Settings
from temporalio.exceptions import ApplicationError

from campaign_worker.publisher import Receipt

CARDS_PREFIX = "cards"
CARD_TYPE = "image/svg+xml"
CARD_REPLY_INVALID = "CardReplyInvalid"


async def save_cards(
    client: httpx.AsyncClient, settings: Settings, campaign_id: str, output: dict[str, Any]
) -> list[Receipt]:
    """Store each card; one receipt per card. Does nothing when no asset library is set up."""
    if not settings.s3_url.strip():
        return []
    base = settings.s3_url.rstrip("/")
    made = await client.put(f"{base}/{settings.s3_bucket}")
    made.raise_for_status()
    receipts = []
    for card in output["cards"]:
        url = f"{base}/{settings.s3_bucket}/{CARDS_PREFIX}/{campaign_id}/{card['name']}"
        stored = await client.put(
            url, content=card["svg"].encode(), headers={"Content-Type": CARD_TYPE}
        )
        stored.raise_for_status()
        etag = stored.headers.get("ETag", "").strip('"')
        if not etag:
            raise ApplicationError(
                f"S3 reply has no ETag for card {card['name']}",
                type=CARD_REPLY_INVALID,
                non_retryable=True,
            )
        receipts.append(Receipt(target=f"{CARDS_PREFIX}/{card['name']}", receipt_id=etag, url=url))
    return receipts
