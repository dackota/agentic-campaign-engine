"""At live depth the worker sends review calls to the brand reviewer Agent, named like its
template under the controller's base URL; at fast depth to the one scripted URL."""

import asyncio
import json
from typing import Any

import httpx
from ace_engine import brand_review, db
from ace_engine.agent_roles import ROLES
from ace_engine.settings import Depth
from campaign_worker.activities import Activities, ReviewJob

from tests.harness.test_settings import _settings

BASE = "http://kagent-controller.kagent:8083/agents/kagent"
PASS = json.dumps({"verdict": "pass", "issues": []})


def _review_paths(depth: Depth, base: str) -> list[str]:
    seen: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        task = {"contextId": "c-1", "artifacts": [{"parts": [{"text": PASS}]}]}
        return httpx.Response(200, json={"result": {"task": task}})

    activities = Activities(_settings(depth=depth, agent_url=base), db.make_engine("sqlite://"))
    job = ReviewJob("camp-1", "email_writer", "report", ROLES["email_writer"], {})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            output: Any = {"subject": "s"}
            await activities._review(client, job, output, 0, None)  # noqa: SLF001

    asyncio.run(go())
    return seen


def test_live_depth_sends_review_calls_to_the_reviewer_agent() -> None:
    paths = _review_paths(Depth.LIVE, BASE)

    assert paths == [f"/agents/kagent/{brand_review.BRAND_REVIEWER.template}"]


def test_fast_depth_sends_review_calls_to_the_one_scripted_url() -> None:
    assert _review_paths(Depth.FAST, "http://agent:8080/") == ["/"]
