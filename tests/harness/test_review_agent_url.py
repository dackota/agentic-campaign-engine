"""At live depth the worker sends review calls to the brand reviewer Agent, named like its
template under the controller's base URL; at fast depth to the one scripted URL."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from ace_engine import brand_review, db
from ace_engine.agent_roles import ROLES
from ace_engine.contracts import AgentOutput
from ace_engine.settings import Depth, Settings
from campaign_worker.activities import Activities, ReviewJob

BASE = "http://kagent-controller.kagent:8083/agents/kagent"


def _settings(depth: Depth, agent_url: str) -> Settings:
    return Settings(
        depth=depth,
        database_url="postgresql://unused",
        temporal_address="localhost:7233",
        temporal_namespace="default",
        agent_url=agent_url,
        marketo_url="http://marketo",
        marketo_client_id="client",
        marketo_client_secret="client-secret",
        marketo_webhook_secret="webhook-secret",
    )


AGENT_DIGEST_LENGTH = 64
PASS = json.dumps({"verdict": "pass", "issues": []})


def _review_paths(depth: Depth, base: str) -> list[str]:
    seen: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        task = {"contextId": "c-1", "artifacts": [{"parts": [{"text": PASS}]}]}
        return httpx.Response(200, json={"result": {"task": task}})

    activities = Activities(_settings(depth, base), db.make_engine("sqlite://"))
    job = ReviewJob("camp-1", "email_writer", "report", ROLES["email_writer"], {})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            output: AgentOutput = {"subject": "s"}
            await activities._review(client, job, output, 0, None)  # noqa: SLF001

    asyncio.run(go())
    return seen


def test_live_depth_sends_review_calls_to_the_reviewer_agent() -> None:
    paths = _review_paths(Depth.LIVE, BASE)

    assert paths == [f"/agents/kagent/{brand_review.BRAND_REVIEWER.template}"]


def test_fast_depth_sends_review_calls_to_the_one_scripted_url() -> None:
    assert _review_paths(Depth.FAST, "http://agent:8080/") == ["/"]


def test_live_depth_reads_the_reviewer_agents_card_for_the_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"name": request.url.path})

    activities = Activities(_settings(Depth.LIVE, BASE), db.make_engine("sqlite://"))
    monkeypatch.setattr(activities, "_cache_team", lambda _campaign_id: "team")
    job = ReviewJob("camp-1", "email_writer", "report", ROLES["email_writer"], {})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            await activities._open_cache(client, job, 2)  # noqa: SLF001

    asyncio.run(go())

    assert sorted(seen) == [
        "/agents/kagent/ace-brand-reviewer/.well-known/agent-card.json",
        "/agents/kagent/ace-email-writer/.well-known/agent-card.json",
    ]


def _cache_digest(monkeypatch: pytest.MonkeyPatch, cards: dict[str, str]) -> str:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": cards[request.url.path.split("/")[3]]})

    activities = Activities(_settings(Depth.LIVE, BASE), db.make_engine("sqlite://"))
    monkeypatch.setattr(activities, "_cache_team", lambda _campaign_id: "team")
    job = ReviewJob("camp-1", "email_writer", "report", ROLES["email_writer"], {})

    async def go() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            return await activities._open_cache(client, job, 2)  # noqa: SLF001

    lookup = asyncio.run(go())
    return str(lookup.key.agent_digest)


def test_cache_digest_fits_its_column_and_changes_with_either_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {"ace-email-writer": "1", "ace-brand-reviewer": "1"}
    digests = {
        _cache_digest(monkeypatch, base),
        _cache_digest(monkeypatch, {**base, "ace-email-writer": "2"}),
        _cache_digest(monkeypatch, {**base, "ace-brand-reviewer": "2"}),
    }

    assert len(digests) == 3
    assert all(len(d) <= AGENT_DIGEST_LENGTH for d in digests)
