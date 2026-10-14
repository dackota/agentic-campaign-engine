"""The worker's activities talking to the scripted agent in-process: a test drives
`Activities` end to end, with no socket and no stack, and reads what the agent was sent."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from campaign_worker.activities import Activities
from sqlalchemy.engine import Engine

from tests.harness.scripted_agent import ScriptedAgent
from tests.support.fake_services import FakeServices
from tests.support.settings import DUMMY_SETTINGS, unit_settings

AGENT_HOST = httpx.URL(DUMMY_SETTINGS.agent_url).host


@dataclass(frozen=True)
class ScriptedWorker:
    agent: ScriptedAgent
    activities: Activities
    services: FakeServices

    def messages_sent(self) -> list[tuple[str, str | None]]:
        """The (messageId, session) of every message the worker sent the agent, in order. A
        session is None for the first message of a conversation."""
        sent = []
        for request in self.services.seen:
            if request.method == "POST" and request.url.host == AGENT_HOST:
                message = json.loads(request.content)["params"]["message"]
                sent.append((message["messageId"], message.get("contextId")))
        return sent


def scripted_worker(engine: Engine, **settings: object) -> ScriptedWorker:
    """`Activities` on `engine` whose agent calls reach a fresh scripted agent. Settings
    override the dummy unit settings."""
    agent = ScriptedAgent()
    transport = FakeServices({AGENT_HOST: agent.app})
    return ScriptedWorker(
        agent, Activities(unit_settings(**settings), engine, transport), transport
    )


def run_step(
    worker: ScriptedWorker,
    campaign_id: uuid.UUID,
    step_id: str,
    report: str,
    review_rounds: int = 0,
) -> dict[str, Any]:
    """Run an agent step as the workflow does: ask the agent, then save what it answered.
    Returns the activity's result."""
    result: dict[str, Any] = asyncio.run(
        worker.activities.run_agent_step(str(campaign_id), report, step_id, {}, review_rounds)
    )
    worker.activities.save_agent_output(str(campaign_id), step_id, result)
    return result
