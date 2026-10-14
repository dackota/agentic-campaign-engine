"""The email writer's reply must meet the email contract: one repair attempt in the same
session recovers a bad first reply, and a second bad reply fails the step for good with no
draft saved. The invoker talks to the scripted agent in-process."""

import asyncio
import json

import httpx
import pytest
from ace_engine import db, invoker
from ace_engine.contracts import EMAIL_DRAFT_SCHEMA
from campaign_worker.activities import AGENT_OUTPUT_INVALID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.exceptions import ApplicationError

from tests.harness.scripted_agent import ScriptedAgent
from tests.support.dag import GOOD_DRAFT, REPORT
from tests.support.scripted_worker import scripted_worker
from tests.support.seed import CampaignSeed, seed_campaign

AGENT_URL = "http://agent.invalid"
KEY = "campaign-1:email_draft"
ONLY_A_SUBJECT = json.dumps({"subject": "only a subject"})
MISSING_FIELDS = json.dumps({"subject": "missing fields"})
NOT_JSON = "not json at all"


class SessionsSent(httpx.AsyncBaseTransport):
    """Passes each request to the agent and keeps the session (contextId) each one named."""

    def __init__(self, agent: ScriptedAgent) -> None:
        self._agent = httpx.ASGITransport(app=agent.app)
        self.sessions: list[str | None] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)["params"]["message"]
        self.sessions.append(message.get("contextId"))
        return await self._agent.handle_async_request(request)


def _invoke(agent: ScriptedAgent, sent: SessionsSent) -> invoker.Invocation:
    async def run() -> invoker.Invocation:
        async with httpx.AsyncClient(transport=sent) as client:
            call = invoker.AgentCall(KEY, "Write an email.", EMAIL_DRAFT_SCHEMA)
            return await invoker.invoke(client, AGENT_URL, call)

    return asyncio.run(run())


def test_one_repair_attempt_recovers_a_bad_first_reply_in_the_same_session() -> None:
    agent = ScriptedAgent()
    agent.script([MISSING_FIELDS, json.dumps(GOOD_DRAFT)])

    sent = SessionsSent(agent)

    invocation = _invoke(agent, sent)

    assert invocation.output == GOOD_DRAFT
    assert agent.message_ids() == [f"{KEY}:1", f"{KEY}:2"]
    # The first question opens a session; the repair goes to the one the agent issued.
    assert sent.sessions == [None, invocation.session_id]


def test_a_reply_that_breaks_the_contract_twice_is_refused_naming_the_contract() -> None:
    agent = ScriptedAgent()
    agent.script([NOT_JSON, ONLY_A_SUBJECT])

    with pytest.raises(invoker.AgentOutputInvalid, match="broke the contract after one repair"):
        _invoke(agent, SessionsSent(agent))

    assert agent.message_ids() == [f"{KEY}:1", f"{KEY}:2"]


def test_the_step_fails_without_a_retry_and_saves_no_draft(sqlite_engine: Engine) -> None:
    campaign_id = seed_campaign(sqlite_engine, CampaignSeed(status=db.DRAFTING))
    worker = scripted_worker(sqlite_engine)
    worker.agent.script([NOT_JSON, ONLY_A_SUBJECT])

    with pytest.raises(ApplicationError, match="contract") as failure:
        asyncio.run(worker.activities.run_agent_step(str(campaign_id), REPORT, "email_draft", {}))

    assert failure.value.type == AGENT_OUTPUT_INVALID
    assert failure.value.non_retryable
    with Session(sqlite_engine) as session:
        assert session.get_one(db.Campaign, campaign_id).draft is None
