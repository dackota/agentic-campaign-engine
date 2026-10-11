"""Activities: the side-effecting steps the campaign workflow runs."""

import asyncio
import uuid
from typing import Any

import httpx
from ace_engine import dag as graph
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
    async def write_email_draft(
        self, campaign_id: str, report: str, step_id: str
    ) -> list[dict[str, Any]]:
        """Both A/B variants of the email, A first; each in its own agent session, keyed by
        the step's idempotency key so no two steps share a session or a message id."""
        await asyncio.to_thread(self._record, campaign_id, step_id, db.STEP_STARTED)
        key = graph.step_key(campaign_id, step_id)
        variants = [(":a", EMAIL_PROMPT), (":b", VARIANT_B_PROMPT)]
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            try:
                return [
                    (
                        await invoker.invoke(
                            client,
                            self._settings.agent_url,
                            session_key=f"{key}{suffix}",
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
    def save_agent_output(
        self, campaign_id: str, step_id: str, drafts: list[dict[str, Any]]
    ) -> None:
        """Store an agent step's A/B email variants and mark the step succeeded."""
        variant_a, variant_b = drafts
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.draft = variant_a
            campaign.variant_b = variant_b
            db.add_event(session, campaign.id, step_id, db.STEP_SUCCEEDED)

    @activity.defn
    def mark_step(self, campaign_id: str, step_id: str, status: str) -> None:
        self._record(campaign_id, step_id, status)

    @activity.defn
    def open_approval(self, campaign_id: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.AWAITING_APPROVAL
            db.add_event(session, campaign.id, db.RUN_STEP, db.AWAITING_APPROVAL)

    @activity.defn
    def mark_failed(self, campaign_id: str, step_id: str, reason: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.FAILED
            campaign.failure_reason = reason
            db.add_event(session, campaign.id, step_id, db.STEP_FAILED, reason)
            db.add_event(session, campaign.id, db.RUN_STEP, db.FAILED, reason)

    @activity.defn
    def finish_run(self, campaign_id: str) -> None:
        """End the run: sent when a publish step sent it, finished when nothing published."""
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.status = db.SENT if campaign.receipt else db.FINISHED
            db.add_event(session, campaign.id, db.RUN_STEP, campaign.status)

    @activity.defn
    async def send_email(
        self,
        campaign_id: str,
        drafts: list[dict[str, Any]],
        step_id: str = publisher.PUBLISH_STEP,
    ) -> str:
        """Publish the approved A/B emails; the receipt id of the Marketo send."""
        campaign = publisher.ApprovedCampaign(
            campaign_id=campaign_id,
            emails=tuple(drafts),
            step_key=graph.step_key(campaign_id, step_id),
        )
        async with httpx.AsyncClient(timeout=self._settings.marketo_timeout_seconds) as client:
            receipts = await publisher.publish(client, [MarketoAdapter(self._settings)], campaign)
        return receipts[0].receipt_id

    @activity.defn
    def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.receipt = receipt
            db.add_event(session, campaign.id, step_id, db.STEP_SUCCEEDED)
