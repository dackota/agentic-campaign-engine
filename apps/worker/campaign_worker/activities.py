"""Activities: the side-effecting steps the campaign workflow runs."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from ace_engine import brand_review, db, invoker
from ace_engine import dag as graph
from ace_engine.agent_roles import Role, message_for, role_for
from ace_engine.contracts import citation_problems
from ace_engine.settings import Settings
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from campaign_worker import notify, publisher
from campaign_worker.content import content_adapters
from campaign_worker.marketo import MarketoAdapter
from campaign_worker.workfront import WorkfrontAdapter

AGENT_OUTPUT_INVALID = "AgentOutputInvalid"
# An agent step's session: the step's idempotency key, so no two steps share a conversation
# or a message id and a retry of the step reuses them. A second reply in the same step
# (variant B) gets its own, suffixed with the variant.


def session_key(campaign_id: str, step_id: str, variant: int = 0) -> str:
    suffix = "" if variant == 0 else f":v{variant}"
    return f"{graph.step_key(campaign_id, step_id)}{suffix}"


@dataclass(frozen=True)
class ReviewJob:
    """What a writer step was asked, so the reviewer's fixes go back to the same sessions."""

    campaign_id: str
    step_id: str
    report: str
    role: Role
    context: dict[str, Any]


@dataclass(frozen=True)
class WriterTurn:
    """What a writer step was asked: the campaign, its report, the step, its role, and what
    earlier steps produced."""

    campaign_id: str
    report: str
    step_id: str
    role: Role
    context: dict[str, Any]


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
                # An agent step's event carries its session; a review event adds the issues.
                db.add_agent_event(
                    session, uuid.UUID(campaign_id), step, status, agent_session, reason
                )

    @activity.defn
    async def run_agent_step(
        self,
        campaign_id: str,
        report: str,
        step_id: str,
        context: dict[str, Any],
        review_rounds: int = 0,
    ) -> dict[str, Any]:
        """Ask the step's agent, each reply in its own session. `context` holds what the
        steps before this one produced. With `review_rounds`, the brand reviewer checks the
        draft and fixes go back to the same sessions. Returns the output and the step's
        session."""
        role = role_for(step_id)
        session = session_key(campaign_id, step_id)
        await asyncio.to_thread(self._record, campaign_id, step_id, db.STEP_STARTED, None, session)
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            try:
                job = ReviewJob(campaign_id, step_id, report, role, context)
                output = await self._writer_outputs(client, job)
                if review_rounds > 0:
                    output = await self._review_loop(client, job, output, review_rounds)
            except invoker.AgentOutputInvalid as exc:
                raise ApplicationError(
                    str(exc), type=AGENT_OUTPUT_INVALID, non_retryable=True
                ) from exc
        if role.checks_citations:
            problems = citation_problems(output, report)
            if problems:
                raise ApplicationError(
                    "research broke the citation rule: " + "; ".join(problems),
                    type=AGENT_OUTPUT_INVALID,
                    non_retryable=True,
                )
        return {"output": output, "session": session}

    async def _review_loop(
        self,
        client: httpx.AsyncClient,
        job: ReviewJob,
        output: Any,
        review_rounds: int,
    ) -> Any:
        """Send the draft to the brand reviewer; on a fix verdict send the issues back to
        the same writer sessions, for at most `review_rounds` rounds (never more than the
        limit). What the reviewer still flags after the last round is flagged for a human."""
        writer_session = session_key(job.campaign_id, job.step_id)
        reviewer_session = f"{graph.step_key(job.campaign_id, job.step_id)}:review"
        fix_rounds = min(review_rounds, brand_review.MAX_FIX_ROUNDS)
        for turn in range(fix_rounds + 1):
            verdict = await invoker.invoke(
                client,
                self._settings.agent_url,
                invoker.AgentCall(
                    session_key=reviewer_session,
                    prompt=brand_review.review_message(output, job.context, job.report),
                    schema=brand_review.VERDICT_SCHEMA,
                    turn=turn,
                ),
            )
            if verdict.output["verdict"] == brand_review.PASS:
                break
            issues = verdict.output["issues"]
            is_last = turn == fix_rounds
            status = brand_review.FLAGGED_STATUS if is_last else brand_review.REVIEW_FIX_STATUS
            await asyncio.to_thread(
                self._record,
                job.campaign_id,
                job.step_id,
                status,
                json.dumps(issues),
                writer_session,
            )
            if is_last:
                break
            output = await self._writer_outputs(client, job, issues, turn + 1)
        return output

    async def _writer_outputs(
        self,
        client: httpx.AsyncClient,
        job: ReviewJob,
        issues: list[dict[str, Any]] | None = None,
        turn: int = 0,
    ) -> Any:
        """Ask each of the writer's sessions: the first draft, or with `issues` the fixes the
        reviewer asked for. The step's output: a list when the role replies more than once."""
        outputs = []
        for variant in range(job.role.replies):
            prompt = message_for(job.role, job.report, job.context, variant)
            if issues is not None:
                prompt = brand_review.fix_message(prompt, issues)
            reply = await invoker.invoke(
                client,
                self._settings.agent_url,
                invoker.AgentCall(
                    session_key=session_key(job.campaign_id, job.step_id, variant),
                    prompt=prompt,
                    schema=job.role.reply_schema,
                    turn=turn,
                ),
            )
            outputs.append(reply.output)
        return outputs if job.role.replies > 1 else outputs[0]

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
    async def send_email(
        self,
        campaign_id: str,
        drafts: list[dict[str, Any]],
        step_id: str = publisher.PUBLISH_STEP,
    ) -> str:
        """Publish the approved A/B emails and the campaign's task; the receipt id of the
        Marketo send. Every target's receipt is stored for the campaign."""
        campaign = publisher.ApprovedCampaign(
            campaign_id=campaign_id,
            emails=tuple(drafts),
            step_key=graph.step_key(campaign_id, step_id),
        )
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
    async def announce_approval(self, campaign_id: str) -> None:
        """Ask for approval in Slack. Does nothing when Slack is not set up, and never
        fails the run."""
        if not self._settings.slack_enabled:
            return
        report, _ = await asyncio.to_thread(self._brief_and_drafts, campaign_id)
        async with httpx.AsyncClient(timeout=self._settings.notify_timeout_seconds) as client:
            await notify.post_to_slack(
                client,
                self._settings,
                f"Campaign {campaign_id} needs approval: {notify.first_line(report)}",
            )

    @activity.defn
    async def announce_published(self, campaign_id: str, receipt: str) -> None:
        """After the send: export the brief and drafts to a Google Doc, then tell Slack. A
        write to an outside account waits for the approval. Each does nothing when its
        credentials are not set, and neither fails the run."""
        if not (self._settings.slack_enabled or self._settings.google_enabled):
            return
        report, drafts = await asyncio.to_thread(self._brief_and_drafts, campaign_id)
        async with httpx.AsyncClient(timeout=self._settings.notify_timeout_seconds) as client:
            await notify.export_to_google_doc(
                client,
                self._settings,
                f"Campaign {campaign_id}",
                notify.doc_text(report, drafts),
            )
            await notify.post_to_slack(
                client,
                self._settings,
                f"Campaign {campaign_id} sent. Marketo receipt: {receipt}",
            )

    def _brief_and_drafts(self, campaign_id: str) -> tuple[str, list[dict[str, Any]]]:
        with Session(self._engine) as session:
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            drafts = [d for d in (campaign.draft, campaign.variant_b) if d]
            return campaign.report, drafts

    @activity.defn
    def mark_sent(self, campaign_id: str, step_id: str, receipt: str) -> None:
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            campaign.receipt = receipt
            db.add_event(session, campaign.id, step_id, db.STEP_SUCCEEDED)

    @activity.defn
    async def publish_content(
        self,
        campaign_id: str,
        drafts: list[dict[str, Any]],
        step_id: str = publisher.PUBLISH_STEP,
    ) -> None:
        """Publish the landing page to the CMS and the email assets to the S3 bucket, and
        keep one receipt per item. Every write is idempotent, so a retry adds nothing."""
        campaign = publisher.ApprovedCampaign(
            campaign_id=campaign_id,
            emails=tuple(drafts),
            step_key=graph.step_key(campaign_id, step_id),
        )
        adapters = content_adapters(self._settings, campaign.emails)
        timeout = self._settings.content_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            receipts = await publisher.publish(client, adapters, campaign)
        await asyncio.to_thread(self._save_receipts, campaign_id, receipts)
