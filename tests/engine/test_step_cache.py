"""The step cache: the key is the step type, the agent revision digest, and a hash of the
input; a saved result is reused only for the same key and team. The agent revision digest
follows the agent's card. The prompt a role sends keeps the stable text first, so a
provider's prefix cache can reuse it."""

import asyncio
from typing import Any

import httpx
import pytest
from ace_engine import db
from ace_engine.agent_roles import EMAIL_ROLE, message_for
from ace_engine.step_cache import CacheKey, StepCache, agent_revision, input_hash
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

STEP_TYPE = "ace-email-writer"
CARD_PATH = "/.well-known/agent-card.json"


def key(step_type: str = STEP_TYPE, revision: str = "rev-1", report: str = "a report") -> CacheKey:
    return CacheKey(step_type, revision, input_hash(report, {}, 0))


@pytest.fixture
def engine() -> Engine:
    created = create_engine("sqlite://")
    db.Base.metadata.create_all(created)
    return created


def test_key_is_step_type_revision_digest_and_input_hash() -> None:
    base = key()

    assert (base.step_type, base.agent_digest) == (STEP_TYPE, "rev-1")
    assert base.input_hash == input_hash("a report", {}, 0)
    assert key() == base
    assert key(step_type="ace-research") != base
    assert key(revision="rev-2") != base
    assert key(report="another report") != base


def test_input_hash_covers_report_context_and_review_rounds() -> None:
    base = input_hash("report", {"strategist": {"a": 1}}, 0)

    assert input_hash("report", {"strategist": {"a": 1}}, 0) == base
    assert input_hash("report!", {"strategist": {"a": 1}}, 0) != base
    assert input_hash("report", {"strategist": {"a": 2}}, 0) != base
    assert input_hash("report", {"strategist": {"a": 1}}, 2) != base


def test_input_hash_ignores_the_order_of_keys() -> None:
    first = input_hash("r", {"x": {"a": 1, "b": 2}, "y": 3}, 0)
    second = input_hash("r", {"y": 3, "x": {"b": 2, "a": 1}}, 0)

    assert first == second


def test_get_misses_until_put_and_then_returns_the_output(engine: Engine) -> None:
    cache = StepCache(engine, team="demand-gen")
    output: Any = [{"subject": "s"}]

    assert cache.get(key()) is None
    cache.put(key(), output, model="m")

    found = cache.get(key())
    assert found is not None
    assert (found.output, found.model) == (output, "m")


@pytest.mark.parametrize(
    "other",
    [key(step_type="ace-research"), key(revision="rev-2"), key(report="other")],
    ids=["step type", "agent revision", "input"],
)
def test_a_key_that_differs_in_any_part_misses(engine: Engine, other: CacheKey) -> None:
    cache = StepCache(engine, team="demand-gen")
    cache.put(key(), {"ok": True}, model="m")

    assert cache.get(other) is None


def test_another_team_never_sees_the_entry(engine: Engine) -> None:
    StepCache(engine, team="demand-gen").put(key(), {"ok": True}, model="m")

    assert StepCache(engine, team="other-team").get(key()) is None


def test_putting_the_same_key_twice_keeps_one_entry(engine: Engine) -> None:
    cache = StepCache(engine, team="demand-gen")
    cache.put(key(), {"n": 1}, model="m")
    cache.put(key(), {"n": 2}, model="m")

    found = cache.get(key())
    assert found is not None and found.output == {"n": 1}


def revision_of(card: Any, url: str = "http://agent/agents/kagent/a") -> str | None:
    """The revision digest the engine reads for an agent whose card is `card` (a status
    code makes the card request fail with it)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(CARD_PATH)
        if isinstance(card, int):
            return httpx.Response(card)
        return httpx.Response(200, json=card)

    async def read() -> str | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await agent_revision(client, url)

    return asyncio.run(read())


def test_agent_revision_follows_the_agent_card() -> None:
    first = revision_of({"name": "a", "version": "1"})
    again = revision_of({"version": "1", "name": "a"}, "http://agent/agents/kagent/a/")
    other = revision_of({"name": "a", "version": "2"})

    assert first is not None and first == again
    assert other is not None and other != first


def test_agent_revision_is_none_when_the_card_cannot_be_read() -> None:
    assert revision_of(500) is None


def test_a_prompt_puts_the_stable_text_first_and_the_report_last() -> None:
    first = message_for(EMAIL_ROLE, "report one", {})
    second = message_for(EMAIL_ROLE, "a different report", {})

    assert first.startswith(EMAIL_ROLE.prompt) and second.startswith(EMAIL_ROLE.prompt)
    assert first.endswith("report one") and second.endswith("a different report")
