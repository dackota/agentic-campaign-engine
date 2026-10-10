"""Activities: the side-effecting steps the campaign workflow runs."""

import asyncio
import uuid
from typing import Any

import httpx
from ace_engine import db, invoker
from ace_engine.contracts import EMAIL_DRAFT_SCHEMA, REPORT_MARKER
from ace_engine.settings import Settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from campaign_worker import publisher
from campaign_worker.marketo import MarketoAdapter

AGENT_OUTPUT_INVALID = "AgentOutputInvalid"
EMAIL_PROMPT = (
    "You are the email writer. Turn the threat report into a marketing email. "
    "Reply with only JSON that has the keys subject, preheader, body, call_to_action.\n\n"
    + REPORT_MARKER
)

VARIANT_B_PROMPT = (
    "You are the email writer. Write variant B of an A/B test for this threat report: "
    "the same facts, a different subject line and angle. "
    "Reply with only JSON that has the keys subject, preheader, body, call_to_action.\n\n"
    + REPORT_MARKER
)


class Activities:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self._settings = settings
        self._engine = engine

    def _record(self, campaign_id: str, step: str, status: str, reason: str | None = None) -> None:
        with Session(self._engine) as session, session.begin():
            db.add_event(session, uuid.UUID(campaign_id), step, status, reason)

    @activity.defn
    async def write_email_draft(self, campaign_id: str, report: str) -> list[dict[str, Any]]:
        """Both A/B variants of the email, A first; each in its own agent session."""
        await asyncio.to_thread(self._record, campaign_id, db.EMAIL_DRAFT_STEP, db.STEP_STARTED)
        variants = [("", EMAIL_PROMPT), ("-b", VARIANT_B_PROMPT)]
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            try:
                return [
                    (
                        await invoker.invoke(
                            client,
                            self._settings.agent_url,
                            session_key=f"campaign-{campaign_id}{suffix}",
                            prompt=f"{prompt}\n{report}",
                            schema=EMAIL_DRAFT_SCHEMA,
                        )
                    ).output
                    for suffix, prompt in variants
                ]
            except invoker.AgentOutputInvalid as exc:
                raise ApplicationError(
                    str(exc), type=AGENT_OUTPUT_INVALID, non_retryable=True
                ) from exc

    @activity.defn
    def save_draft(self, campaign_id: str, drafts: list[dict[str, Any]]) -> None:
        variant_a, variant_b = drafts
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.draft = variant_a
            campaign.variant_b = variant_b
            campaign.status = db.AWAITING_APPROVAL
            db.add_event(session, campaign.id, db.EMAIL_DRAFT_STEP, db.STEP_SUCCEEDED)
            db.add_event(session, campaign.id, db.RUN_STEP, db.AWAITING_APPROVAL)

    @activity.defn
    def mark_failed(self, campaign_id: str, reason: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.FAILED
            campaign.failure_reason = reason
            if campaign.draft is None:  # a failed send is not an email-draft failure
                db.add_event(session, campaign.id, db.EMAIL_DRAFT_STEP, db.STEP_FAILED, reason)
            db.add_event(session, campaign.id, db.RUN_STEP, db.FAILED, reason)

    @activity.defn
    async def send_email(self, campaign_id: str, drafts: list[dict[str, Any]]) -> str:
        """Publish the approved A/B emails; the receipt id of the Marketo send."""
        campaign = publisher.ApprovedCampaign(campaign_id=campaign_id, emails=tuple(drafts))
        async with httpx.AsyncClient(timeout=self._settings.marketo_timeout_seconds) as client:
            receipts = await publisher.publish(client, [MarketoAdapter(self._settings)], campaign)
        return receipts[0].receipt_id

    @activity.defn
    def mark_sent(self, campaign_id: str, receipt: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.SENT
            campaign.receipt = receipt
