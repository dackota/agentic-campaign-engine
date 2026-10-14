"""Every step of a run has its own idempotency key: the agent's messages, the publish
program, and the step list the API shows all carry it, the same on every attempt."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from ace_engine import dag as graph
from ace_engine import db
from campaign_api.main import CampaignOut
from campaign_worker.activities import Activities, session_key
from fake_marketo import app as fake_marketo
from fake_marketo.app import MarketoConfig
from sqlalchemy.engine import Engine

from tests.engine.agent_replies import task_reply
from tests.support.campaigns import add_campaign
from tests.support.dag import DRAFT_APPROVE_PUBLISH, GOOD_DRAFT, REPORT
from tests.support.settings import unit_settings

CAMPAIGN_ID = str(uuid.uuid4())
PARALLEL_STEPS = ("brief", "writer_a", "writer_b")


def test_each_step_has_its_own_key_naming_its_campaign_and_the_same_on_every_call() -> None:
    steps = [s["id"] for s in DRAFT_APPROVE_PUBLISH["steps"]]

    keys = [graph.step_key(CAMPAIGN_ID, s) for s in steps]

    assert len(set(keys)) == len(steps)
    assert all(CAMPAIGN_ID in k for k in keys)
    assert keys == [graph.step_key(CAMPAIGN_ID, s) for s in steps]
    assert graph.step_key(str(uuid.uuid4()), steps[0]) != keys[0]


def test_the_step_list_the_api_shows_carries_each_steps_key() -> None:
    campaign = db.Campaign(
        id=uuid.uuid4(),
        report=REPORT,
        team="demand-gen",
        created_by="u",
        status=db.DRAFTING,
        dag=DRAFT_APPROVE_PUBLISH,
        created_at=datetime.now(UTC),
    )

    shown = CampaignOut.of(campaign, [], None).steps

    assert {s["id"]: s["idempotency_key"] for s in shown} == {
        s["id"]: graph.step_key(str(campaign.id), s["id"]) for s in DRAFT_APPROVE_PUBLISH["steps"]
    }


def test_a_second_reply_of_a_step_has_a_session_of_its_own_under_the_steps_key() -> None:
    key = graph.step_key(CAMPAIGN_ID, "writer_a")

    assert session_key(CAMPAIGN_ID, "writer_a") == key
    assert session_key(CAMPAIGN_ID, "writer_a", variant=1) == f"{key}:v1"
    assert session_key(CAMPAIGN_ID, "writer_b") != key


def test_every_agent_message_of_a_step_is_sent_under_that_steps_key(sqlite_engine: Engine) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    message_ids: list[str] = []

    def agent(request: httpx.Request) -> httpx.Response:
        message_ids.append(json.loads(request.content)["params"]["message"]["messageId"])
        return httpx.Response(200, json=task_reply(GOOD_DRAFT))

    activities = Activities(
        unit_settings(agent_url="http://agent.test"), sqlite_engine, httpx.MockTransport(agent)
    )

    async def run_steps() -> None:
        for step_id in PARALLEL_STEPS:
            await activities.run_agent_step(campaign_id, REPORT, step_id, {})

    asyncio.run(run_steps())

    for step_id in PARALLEL_STEPS:
        key = graph.step_key(campaign_id, step_id)
        # One first message per A/B variant, each under the step's own key.
        firsts = [m for m in message_ids if m.startswith(f"{key}:") and m.endswith(":1")]
        assert sorted(firsts) == sorted([f"{key}:1", f"{key}:v1:1"]), (step_id, message_ids)
    assert len(message_ids) == 2 * len(PARALLEL_STEPS)


def test_the_publish_program_is_named_after_the_publish_steps_key(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    monkeypatch.setattr(fake_marketo, "_post_activity", lambda *_: None)
    monkeypatch.setattr(fake_marketo, "_deliver_engagement", lambda *_: None)
    config = MarketoConfig("id", "secret", "http://127.0.0.1:9/dead", "hook")
    marketo = fake_marketo.create_app(config)
    settings = unit_settings(
        marketo_url="http://marketo.test", marketo_client_id="id", marketo_client_secret="secret"
    )
    activities = Activities(settings, sqlite_engine, httpx.ASGITransport(app=marketo))

    asyncio.run(activities.send_email(campaign_id, [GOOD_DRAFT, GOOD_DRAFT], "publish"))

    async def programs() -> list[dict[str, object]]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=marketo)) as http:
            token = await http.post(
                "http://marketo.test/identity/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "id",
                    "client_secret": "secret",
                },
            )
            listed = await http.get(
                "http://marketo.test/rest/asset/v1/programs.json",
                params={"externalId": campaign_id},
                headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            )
        found: list[dict[str, object]] = listed.json()["result"]
        return found

    [program] = asyncio.run(programs())
    step_key = graph.step_key(campaign_id, "publish")
    assert program["name"] == f"{step_key}:marketo"
