"""Activities: the side-effecting steps the campaign workflow runs."""

import asyncio
import uuid
from typing import Any

import httpx
from ace_engine import db, invoker
from ace_engine.agent_roles import message_for, role_for
from ace_engine.contracts import citation_problems
from ace_engine.settings import Settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from campaign_worker import publisher
from campaign_worker.marketo import MarketoAdapter
from campaign_worker.workfront import WorkfrontAdapter

AGENT_OUTPUT_INVALID = "AgentOutputInvalid"
# An agent step's session: one per step per campaign, so no two steps share a conversation.
# A second reply in the same step (variant B) gets its own, suffixed with the variant.


def session_key(campaign_id: str, step_id: str, variant: int = 0) -> str:
    suffix = "" if variant == 0 else f"-v{variant}"
    return f"campaign-{campaign_id}-{step_id}{suffix}"


class Activities:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self._settings = settings
        self._engine = engine

    def _record(
        self,
        campaign_id: str,
        step: str,
        status: str,
        reason: str | None = None,
        agent_session: str | None = None,
    ) -> None:
        with Session(self._engine) as session, session.begin():
            if agent_session is None:
                db.add_event(session, uuid.UUID(campaign_id), step, status, reason)
            else:
                # Agent steps carry a session and never a reason.
                db.add_agent_event(session, uuid.UUID(campaign_id), step, status, agent_session)

    @activity.defn
    async def run_agent_step(
        self, campaign_id: str, report: str, step_id: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Ask the step's agent, each reply in its own session. `context` holds what the
        steps before this one produced. Returns the output and the step's session."""
        role = role_for(step_id)
        session = session_key(campaign_id, step_id)
        await asyncio.to_thread(self._record, campaign_id, step_id, db.STEP_STARTED, None, session)
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            try:
                replies = [
                    (
                        await invoker.invoke(
                            client,
                            self._settings.agent_url,
                            session_key=session_key(campaign_id, step_id, variant),
                            prompt=message_for(role, report, context, variant),
                            schema=role.reply_schema,
                        )
                    ).output
                    for variant in range(role.replies)
                ]
            except invoker.AgentOutputInvalid as exc:
                raise ApplicationError(
                    str(exc), type=AGENT_OUTPUT_INVALID, non_retryable=True
                ) from exc
        output: Any = replies if role.replies > 1 else replies[0]
        if role.checks_citations:
            problems = citation_problems(output, report)
            if problems:
                raise ApplicationError(
                    "research broke the citation rule: " + "; ".join(problems),
                    type=AGENT_OUTPUT_INVALID,
                    non_retryable=True,
                )
        return {"output": output, "session": session}

    @activity.defn
    def save_agent_output(self, campaign_id: str, step_id: str, result: dict[str, Any]) -> None:
        """Store an agent step's output and mark the step succeeded. The email writer's
        two emails become the campaign's draft and its A/B variant."""
        output, agent_session = result["output"], result["session"]
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            session.merge(
                db.StepOutput(
                    campaign_id=campaign.id, step=step_id, session=agent_session, output=output
                )
            )
            if role_for(step_id).writes_draft:
                campaign.draft, campaign.variant_b = output
            db.add_agent_event(session, campaign.id, step_id, db.STEP_SUCCEEDED, agent_session)

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
    async def send_email(self, campaign_id: str, drafts: list[dict[str, Any]]) -> str:
        """Publish the approved A/B emails and the campaign's task; the receipt id of the
        Marketo send. Every target's receipt is stored for the campaign."""
        campaign = publisher.ApprovedCampaign(campaign_id=campaign_id, emails=tuple(drafts))
        adapters: list[publisher.Adapter] = [MarketoAdapter(self._settings)]
        if self._settings.has_workfront:
            adapters.append(WorkfrontAdapter(self._settings))
        async with httpx.AsyncClient(timeout=self._settings.marketo_timeout_seconds) as client:
            receipts = await publisher.publish(client, adapters, campaign)
        await asyncio.to_thread(self._save_receipts, campaign_id, receipts)
        return receipts[0].receipt_id

    def _save_receipts(self, campaign_id: str, receipts: list[publisher.Receipt]) -> None:
        for r in receipts:
            db.save_receipt(self._engine, uuid.UUID(campaign_id), r.target, r.receipt_id, r.url)

    @activity.defn
    def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.receipt = receipt
            db.add_event(session, campaign.id, step_id, db.STEP_SUCCEEDED)
