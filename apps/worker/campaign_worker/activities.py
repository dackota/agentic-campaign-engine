"""Activities: the side-effecting steps the campaign workflow runs."""

import uuid
from typing import Any

import httpx
from ace_engine import db, invoker
from ace_engine.contracts import EMAIL_DRAFT_SCHEMA
from ace_engine.settings import Settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

AGENT_OUTPUT_INVALID = "AgentOutputInvalid"
REPORT_MARKER = "THREAT REPORT:"
EMAIL_PROMPT = (
    "You are the email writer. Turn the threat report into a marketing email. "
    "Reply with only JSON that has the keys subject, preheader, body, call_to_action.\n\n"
    + REPORT_MARKER
)


class Activities:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self._settings = settings
        self._engine = engine

    @activity.defn
    async def write_email_draft(self, campaign_id: str, report: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            try:
                result = await invoker.invoke(
                    client,
                    self._settings.agent_url,
                    session_key=f"campaign-{campaign_id}",
                    prompt=f"{EMAIL_PROMPT}\n{report}",
                    schema=EMAIL_DRAFT_SCHEMA,
                )
            except invoker.AgentOutputInvalid as exc:
                raise ApplicationError(
                    str(exc), type=AGENT_OUTPUT_INVALID, non_retryable=True
                ) from exc
        return result.output

    @activity.defn
    def save_draft(self, campaign_id: str, draft: dict[str, Any]) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.draft = draft
            campaign.status = db.AWAITING_APPROVAL

    @activity.defn
    def mark_failed(self, campaign_id: str, reason: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.FAILED
            campaign.failure_reason = reason

    @activity.defn
    async def send_email(self, campaign_id: str, draft: dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            response = await client.post(
                f"{self._settings.marketo_url}/rest/v1/emails/send",
                json={"campaign_id": campaign_id, **draft},
            )
            response.raise_for_status()
        receipt: str = response.json()["result"][0]["receiptId"]
        return receipt

    @activity.defn
    def mark_sent(self, campaign_id: str, receipt: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.SENT
            campaign.receipt = receipt
