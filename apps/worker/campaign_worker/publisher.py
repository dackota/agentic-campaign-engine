"""Publisher: `publish(client, adapters, campaign)` returns one receipt per target.

Each target (Marketo today; Workfront, the CMS, the asset library, and Slack later) is an
adapter. An adapter's writes are idempotent, keyed by the campaign and the publish step,
so a retried step returns the first receipt and never writes twice.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# The publish step of the default workflow.
PUBLISH_STEP = "publish"


@dataclass(frozen=True)
class ApprovedCampaign:
    campaign_id: str
    # The approved emails in A/B order: variant A first.
    emails: tuple[dict[str, Any], ...]
    # The idempotency key of the publish step that sends it.
    step_key: str


@dataclass(frozen=True)
class Receipt:
    target: str
    receipt_id: str
    url: str


class Adapter(Protocol):
    target: str

    async def publish(
        self, client: httpx.AsyncClient, campaign: ApprovedCampaign, idempotency_key: str
    ) -> Receipt: ...


def idempotency_key(campaign: ApprovedCampaign, target: str) -> str:
    """One key per campaign, step, and target: the same on every retry of the step."""
    return f"{campaign.step_key}:{target}"


async def publish(
    client: httpx.AsyncClient, adapters: list[Adapter], campaign: ApprovedCampaign
) -> list[Receipt]:
    return [
        await adapter.publish(client, campaign, idempotency_key(campaign, adapter.target))
        for adapter in adapters
    ]
