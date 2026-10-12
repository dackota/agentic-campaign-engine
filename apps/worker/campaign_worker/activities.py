"""Activities: the side-effecting steps the campaign workflow runs."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from ace_engine import brand_review, cost, db, invoker, step_cache, telemetry
from ace_engine import dag as graph
from ace_engine.agent_roles import Role, agent_url_for, message_for, role_for
from ace_engine.contracts import AgentOutput, citation_problems
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
SERVICE = "campaign-worker"
# An agent step's session: the step's idempotency key, so no two steps share a conversation
# or a message id and a retry of the step reuses them. A second reply in the same step
# (variant B) gets its own, suffixed with the variant.


def session_key(campaign_id: str, step_id: str, variant: int = 0) -> str:
    suffix = "" if variant == 0 else f":v{variant}"
    return f"{graph.step_key(campaign_id, step_id)}{suffix}"


def _check_citations(role: Role, output: AgentOutput, report: str) -> None:
    """Fail the step, without a retry, when a research output breaks the citation rule."""
    if role.checks_citations and isinstance(output, dict):
        problems = citation_problems(output, report)
        if problems:
            raise ApplicationError(
                "research broke the citation rule: " + "; ".join(problems),
                type=AGENT_OUTPUT_INVALID,
                non_retryable=True,
            )


def _cache_hit_result(hit: step_cache.CachedStep, session: str) -> dict[str, Any]:
    """The activity result for a saved output: no tokens, so no cost."""
    usage = cost.Usage(model=hit.model, input_tokens=0, output_tokens=0)
    return {
        "output": hit.output,
        "session": session,
        "usage": usage.as_dict(),
        "cache_hit": True,
    }


@dataclass(frozen=True)
class StepCacheLookup:
    """One step's cache and its key."""

    cache: step_cache.StepCache
    key: step_cache.CacheKey

    def lookup(self) -> step_cache.CachedStep | None:
        return self.cache.get(self.key)

    def save(self, output: Any, model: str) -> None:
        self.cache.put(self.key, output, model)


@dataclass(frozen=True)
class ReviewJob:
    """What a writer step was asked, so the reviewer's fixes go back to the same sessions."""

    campaign_id: str
    step_id: str
    report: str
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
                event = db.add_agent_event(
                    session, uuid.UUID(campaign_id), step, status, agent_session
                )
                event.reason = reason

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
        job = ReviewJob(campaign_id, step_id, report, role, context)
        async with httpx.AsyncClient(timeout=self._settings.agent_timeout_seconds) as client:
            cache = await self._open_cache(client, job, review_rounds)
            hit = await asyncio.to_thread(cache.lookup) if cache is not None else None
            # A saved result costs nothing, so a spent budget does not stop it.
            if hit is None and await asyncio.to_thread(self._is_budget_spent, campaign_id):
                raise ApplicationError(
                    "the campaign's budget is spent", type=cost.BUDGET_SPENT, non_retryable=True
                )
            await asyncio.to_thread(
                self._record, campaign_id, step_id, db.STEP_STARTED, None, session
            )
            if hit is not None:
                return _cache_hit_result(hit, session)
            is_flagged = False
            try:
                with telemetry.span(SERVICE, f"invoke_agent {step_id}", operation="invoke_agent"):
                    output, usage, writer_sessions = await self._writer_outputs(client, job)
                    if review_rounds > 0:
                        output, usage, is_flagged = await self._review_loop(
                            client, job, (output, usage, writer_sessions), review_rounds
                        )
            except invoker.AgentOutputInvalid as exc:
                raise ApplicationError(
                    str(exc), type=AGENT_OUTPUT_INVALID, non_retryable=True
                ) from exc
        _check_citations(role, output, report)
        await self._save_unless_flagged(cache, output, usage, is_flagged)
        return {"output": output, "session": session, "usage": usage.as_dict()}

    @staticmethod
    async def _save_unless_flagged(
        cache: StepCacheLookup | None, output: AgentOutput, usage: cost.Usage, is_flagged: bool
    ) -> None:
        """Save a clean output for reuse. One the reviewer still flags is left for a human."""
        if cache is not None and not is_flagged:
            await asyncio.to_thread(cache.save, output, usage.model)

    async def _open_cache(
        self, client: httpx.AsyncClient, job: ReviewJob, review_rounds: int
    ) -> StepCacheLookup | None:
        """The step's cache entry, or None when the campaign did not opt in or the agent's
        revision cannot be read (such a step always runs)."""
        team = await asyncio.to_thread(self._cache_team, job.campaign_id)
        if team is None:
            return None
        urls = [agent_url_for(self._settings.agent_url, self._settings.depth, job.role)]
        if review_rounds > 0:
            urls.append(self._settings.agent_url)
        revisions = [await step_cache.agent_revision(client, url) for url in urls]
        digests = [r for r in revisions if r is not None]
        if len(digests) < len(revisions):
            return None
        key = step_cache.CacheKey(
            step_type=job.role.template,
            agent_digest=":".join(digests),
            input_hash=step_cache.input_hash(job.report, job.context, review_rounds),
        )
        return StepCacheLookup(step_cache.StepCache(self._engine, team), key)

    def _cache_team(self, campaign_id: str) -> str | None:
        """The campaign's team when it uses the step cache, else None."""
        with Session(self._engine) as session:
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            return campaign.team if campaign.use_step_cache else None

    def _is_budget_spent(self, campaign_id: str) -> bool:
        """True when the campaign has a budget and its model calls have used all of it."""
        with Session(self._engine) as session:
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            return cost.is_budget_spent(
                campaign.budget_micros, db.spent_micros(session, campaign.id)
            )

    async def _review_loop(
        self,
        client: httpx.AsyncClient,
        job: ReviewJob,
        draft: tuple[AgentOutput, cost.Usage, tuple[str, ...]],
        review_rounds: int,
    ) -> tuple[AgentOutput, cost.Usage, bool]:
        """Send the draft to the brand reviewer; on a fix verdict send the issues back to
        the same writer sessions, for at most `review_rounds` rounds (never more than the
        limit). What the reviewer still flags after the last round is flagged for a human.
        `draft` is the writers' output, its tokens, and the sessions the agents issued.
        Returns the output, the tokens of every call so far, and whether a human is left to
        look at what the reviewer still flags."""
        output, usage, writer_sessions = draft
        is_flagged = False
        reviewer_session_id: str | None = None
        writer_session = session_key(job.campaign_id, job.step_id)
        fix_rounds = min(review_rounds, brand_review.MAX_FIX_ROUNDS)
        for turn in range(fix_rounds + 1):
            verdict = await self._review(client, job, output, turn, reviewer_session_id)
            reviewer_session_id = verdict.session_id
            usage = usage + verdict.usage
            if verdict.output["verdict"] == brand_review.PASS:
                break
            issues = verdict.output["issues"]
            is_last = turn == fix_rounds
            status = db.FLAGGED if is_last else db.REVIEW_FIX
            await asyncio.to_thread(
                self._record,
                job.campaign_id,
                job.step_id,
                status,
                json.dumps(issues),
                writer_session,
            )
            if is_last:
                is_flagged = True
                break
            output, fix_usage, writer_sessions = await self._writer_outputs(
                client, job, issues, turn + 1, writer_sessions
            )
            usage = usage + fix_usage
        return output, usage, is_flagged

    async def _review(
        self,
        client: httpx.AsyncClient,
        job: ReviewJob,
        output: AgentOutput,
        turn: int,
        session_id: str | None,
    ) -> invoker.Invocation:
        reviewer_session = f"{graph.step_key(job.campaign_id, job.step_id)}:review"
        return await invoker.invoke(
            client,
            self._settings.agent_url,
            invoker.AgentCall(
                session_key=reviewer_session,
                prompt=brand_review.review_message(output, job.context, job.report),
                schema=brand_review.VERDICT_SCHEMA,
                turn=turn,
                session_id=session_id,
            ),
        )

    async def _writer_outputs(
        self,
        client: httpx.AsyncClient,
        job: ReviewJob,
        issues: list[dict[str, Any]] | None = None,
        turn: int = 0,
        sessions: tuple[str, ...] = (),
    ) -> tuple[AgentOutput, cost.Usage, tuple[str, ...]]:
        """Ask each of the writer's sessions: the first draft, or with `issues` the fixes the
        reviewer asked for. The step's output (a list when the role replies more than once)
        the tokens the calls used, and the sessions the agent issued (`sessions` are the ones
        a fix goes back to)."""
        outputs = []
        issued = []
        usage = cost.NO_USAGE
        for variant in range(job.role.replies):
            prompt = message_for(job.role, job.report, job.context, variant)
            if issues is not None:
                prompt = brand_review.fix_message(prompt, issues)
            reply = await invoker.invoke(
                client,
                agent_url_for(self._settings.agent_url, self._settings.depth, job.role),
                invoker.AgentCall(
                    session_key=session_key(job.campaign_id, job.step_id, variant),
                    prompt=prompt,
                    schema=job.role.reply_schema,
                    turn=turn,
                    session_id=sessions[variant] if sessions else None,
                ),
            )
            outputs.append(reply.output)
            issued.append(reply.session_id)
            usage = usage + reply.usage
        return (outputs if job.role.replies > 1 else outputs[0]), usage, tuple(issued)

    @activity.defn
    def save_agent_output(self, campaign_id: str, step_id: str, result: dict[str, Any]) -> None:
        """Store an agent step's output and mark the step succeeded. The email writer's
        two emails become the campaign's draft and its A/B variant."""
        output, agent_session = result["output"], result["session"]
        usage = cost.usage_from(result.get("usage"))
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            session.merge(
                db.StepOutput(
                    campaign_id=campaign.id, step=step_id, session=agent_session, output=output
                )
            )
            session.merge(
                db.StepUsage(
                    campaign_id=campaign.id,
                    step=step_id,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_micros=usage.cost_micros,
                    cache_hit=bool(result.get("cache_hit")),
                )
            )
            if role_for(step_id).writes_draft:
                campaign.draft, campaign.variant_b = output
            event = db.add_agent_event(
                session, campaign.id, step_id, db.STEP_SUCCEEDED, agent_session
            )
            event.tokens = usage.total_tokens or None

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
    def pause_for_budget(self, campaign_id: str) -> None:
        """Hold the run at its budget until the owner raises it."""
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            spent = cost.to_dollars(db.spent_micros(session, campaign.id))
            budget = cost.to_dollars(campaign.budget_micros or 0)
            reason = f"budget of ${budget:.4f} reached: ${spent:.4f} spent"
            campaign.status = db.BUDGET_PAUSED
            db.add_event(session, campaign.id, db.RUN_STEP, db.BUDGET_PAUSED, reason)

    @activity.defn
    def resume_after_budget(self, campaign_id: str) -> None:
        """The owner raised the budget: the paused run drafts again. Writers that waited
        together each call this; only the first changes anything."""
        with Session(self._engine) as session, session.begin():
            campaign = session.get_one(db.Campaign, uuid.UUID(campaign_id))
            if campaign.status != db.BUDGET_PAUSED:
                return
            campaign.status = db.DRAFTING
            db.add_event(session, campaign.id, db.RUN_STEP, db.DRAFTING)

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
