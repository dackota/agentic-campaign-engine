"""The worker's activities talking to the scripted agent in-process: a test drives
`Activities` end to end, with no socket and no stack, and reads what the agent was sent."""

from dataclasses import dataclass

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


def scripted_worker(engine: Engine, **settings: object) -> ScriptedWorker:
    """`Activities` on `engine` whose agent calls reach a fresh scripted agent. Settings
    override the dummy unit settings."""
    agent = ScriptedAgent()
    transport = FakeServices({AGENT_HOST: agent.app})
    return ScriptedWorker(agent, Activities(unit_settings(**settings), engine, transport))
