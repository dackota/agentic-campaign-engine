"""A called A/B winner becomes a learning. The team reads it at GET /learnings and through the
learnings search MCP tool; another team sees none of it, as row-level security is the only team
filter; only an approver deletes one, and a deleted one is never learned again. What needs
pgvector or row-level security runs on a real Postgres; the rest on SQLite."""

import json
import uuid
from typing import Any

import pytest
from ace_engine import learnings
from ace_engine.db import EMBEDDING_DIMENSIONS
from ace_engine.learnings import Winner
from ace_engine.row_security import for_team
from ace_mcp import learnings as learnings_mcp
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.support.campaigns import OTHER_TEAM, TEAM, add_campaign
from tests.support.dag import APPROVER, GOOD_DRAFT, OWNER, REPORT, signed_headers
from tests.support.settings import DUMMY_SETTINGS

VARIANT_B = {**GOOD_DRAFT, "subject": "Another subject", "call_to_action": "Read now"}
TITLE = REPORT.split("\n", 1)[0]
A_WINS = Winner("A", 0.97, {"A": {"opens": 80, "clicks": 10}, "B": {"opens": 30, "clicks": 5}})
B_WINS = Winner("B", 0.99, {"A": {"opens": 10, "clicks": 1}, "B": {"opens": 90, "clicks": 20}})
WEBHOOK = "/webhooks/marketo"


def _campaign(engine: Engine, **fields: object) -> uuid.UUID:
    return add_campaign(engine, draft=GOOD_DRAFT, variant_b=VARIANT_B, **fields)


def _learn(engine: Engine, campaign_id: uuid.UUID, winner: Winner = A_WINS) -> bool:
    return learnings.learn_from_winner(engine, campaign_id, winner, learnings.stand_in_embedding)


def _search(engine: Engine, team: str, query: str) -> list[dict[str, Any]]:
    mcp = TestClient(learnings_mcp.create_app(engine, team, learnings.stand_in_embedding))
    response = mcp.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": learnings_mcp.SEARCH_TOOL, "arguments": {"query": query}},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    found: list[dict[str, Any]] = json.loads(result["content"][0]["text"])
    return found


def test_a_called_winner_creates_one_learning_with_its_text_reason_and_metrics(
    sqlite_engine: Engine,
) -> None:
    campaign_id = _campaign(sqlite_engine)

    assert _learn(sqlite_engine, campaign_id) is True

    [found] = learnings.list_learnings(sqlite_engine)
    learning = found.learning
    assert learning.campaign_id == campaign_id
    assert found.campaign_title == TITLE
    assert learning.text == "\n".join(
        [GOOD_DRAFT["subject"], GOOD_DRAFT["preheader"], GOOD_DRAFT["call_to_action"]]
    )
    assert learning.reason == (
        "Variant A won on opens (80 opens for A against 30 opens for B), 97% confident."
    )
    assert learning.metrics == {
        "winner": "A",
        "confidence": 0.97,
        "engagement": {"A": {"opens": 80, "clicks": 10}, "B": {"opens": 30, "clicks": 5}},
    }


def test_the_learning_of_a_variant_b_win_holds_variant_bs_lines(sqlite_engine: Engine) -> None:
    campaign_id = _campaign(sqlite_engine)

    assert _learn(sqlite_engine, campaign_id, B_WINS) is True

    [found] = learnings.list_learnings(sqlite_engine)
    assert found.learning.text.splitlines()[0] == "Another subject"
    assert "Read now" in found.learning.text
    assert found.learning.reason.startswith("Variant B won on opens")


def test_a_campaign_learns_once_and_a_campaign_with_no_winning_email_learns_nothing(
    sqlite_engine: Engine,
) -> None:
    campaign_id = _campaign(sqlite_engine)
    no_email = add_campaign(sqlite_engine)

    assert _learn(sqlite_engine, campaign_id) is True
    assert _learn(sqlite_engine, campaign_id, B_WINS) is False
    assert _learn(sqlite_engine, no_email) is False
    assert _learn(sqlite_engine, uuid.uuid4()) is False

    assert len(learnings.list_learnings(sqlite_engine)) == 1


def test_a_learning_is_stored_with_an_embedding_of_the_column_size(
    postgres_engine: Engine,
) -> None:
    campaign_id = _campaign(postgres_engine)
    _learn(postgres_engine, campaign_id)

    [found] = learnings.list_learnings(postgres_engine)

    with postgres_engine.connect() as conn:
        dims = conn.execute(
            text("SELECT vector_dims(embedding) FROM learnings WHERE id = :id"),
            {"id": found.learning.id},
        ).scalar_one()
    assert dims == EMBEDDING_DIMENSIONS


def test_another_team_neither_reads_nor_deletes_the_learning(postgres_engine: Engine) -> None:
    campaign_id = _campaign(postgres_engine, team=TEAM)
    _learn(postgres_engine, campaign_id)
    [found] = learnings.list_learnings(for_team(postgres_engine, TEAM))
    other_team = for_team(postgres_engine, OTHER_TEAM)

    assert learnings.list_learnings(other_team) == []
    assert learnings.remove(other_team, found.learning.id) is False
    assert len(learnings.list_learnings(for_team(postgres_engine, TEAM))) == 1


def test_the_search_tool_returns_the_learning_for_a_matching_query_and_only_to_its_team(
    postgres_engine: Engine,
) -> None:
    campaign_id = _campaign(postgres_engine, team=TEAM)
    _learn(postgres_engine, campaign_id)
    [found] = learnings.list_learnings(for_team(postgres_engine, TEAM))
    learning = found.learning

    own = _search(postgres_engine, TEAM, learning.text)
    other_team = _search(postgres_engine, OTHER_TEAM, learning.text)

    assert own[0]["id"] == str(learning.id)
    assert own[0]["text"] == learning.text
    assert own[0]["reason"] == learning.reason
    assert other_team == []


def test_a_removed_learning_leaves_the_list_and_the_search_but_the_row_stays(
    postgres_engine: Engine,
) -> None:
    campaign_id = _campaign(postgres_engine, team=TEAM)
    _learn(postgres_engine, campaign_id)
    team = for_team(postgres_engine, TEAM)
    [found] = learnings.list_learnings(team)

    assert learnings.remove(team, found.learning.id) is True
    assert learnings.remove(team, found.learning.id) is False

    assert learnings.list_learnings(team) == []
    assert _search(postgres_engine, TEAM, found.learning.text) == []
    with postgres_engine.connect() as conn:
        deleted_at = conn.execute(
            text("SELECT deleted_at FROM learnings WHERE id = :id"), {"id": found.learning.id}
        ).scalar_one()
    assert deleted_at is not None


def test_a_deleted_learning_stays_deleted_when_the_campaign_wins_again(
    sqlite_engine: Engine,
) -> None:
    campaign_id = _campaign(sqlite_engine)
    _learn(sqlite_engine, campaign_id)
    [found] = learnings.list_learnings(sqlite_engine)
    assert learnings.remove(sqlite_engine, found.learning.id) is True

    assert _learn(sqlite_engine, campaign_id) is False

    assert learnings.list_learnings(sqlite_engine) == []


# The route: signed open webhooks call a winner, the team reads the learning, an approver
# deletes it, and a late open does not bring it back.


def _open(client: TestClient, campaign_id: uuid.UUID, variant: str, event_id: str) -> int:
    body = json.dumps(
        {"id": event_id, "type": "open", "campaignId": str(campaign_id), "variant": variant}
    ).encode()
    secret = DUMMY_SETTINGS.marketo_webhook_secret
    response = client.post(WEBHOOK, content=body, headers=signed_headers(secret, body))
    status: int = response.status_code
    return status


def _as(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {email}"}


def _shown(client: TestClient, campaign_id: uuid.UUID) -> list[dict[str, Any]]:
    response = client.get("/learnings", headers=_as(OWNER))
    assert response.status_code == 200, response.text
    return [i for i in response.json() if i["campaign_id"] == str(campaign_id)]


def test_opens_that_call_a_winner_show_one_learning_an_approver_deletes_and_late_opens_keep_gone(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = _campaign(sqlite_engine)
    for n in range(40):
        assert _open(app_client, campaign_id, "A", f"open-a-{n}") == 202
    assert _shown(app_client, campaign_id) == []
    for n in range(5):
        assert _open(app_client, campaign_id, "B", f"open-b-{n}") == 202

    [learning] = _shown(app_client, campaign_id)

    assert learning["reason"].startswith("Variant A won")
    assert learning["campaign_title"] == TITLE
    assert learning["metrics"]["winner"] == "A"
    assert learning["metrics"]["confidence"] >= 0.95
    assert set(learning["metrics"]["engagement"]) == {"A", "B"}
    assert GOOD_DRAFT["subject"] in learning["text"]
    path = f"/learnings/{learning['id']}"
    assert app_client.delete(path, headers=_as(OWNER)).status_code == 403
    assert app_client.delete(path, headers=_as(APPROVER)).status_code == 200
    assert _shown(app_client, campaign_id) == []
    assert app_client.delete(path, headers=_as(APPROVER)).status_code == 404
    assert _open(app_client, campaign_id, "A", "late-open") == 202
    assert _shown(app_client, campaign_id) == []


@pytest.mark.parametrize("variant_opens", [(10, 10), (14, 15), (30, 30)])
def test_opens_that_do_not_separate_the_variants_call_no_winner(
    app_client: TestClient, sqlite_engine: Engine, variant_opens: tuple[int, int]
) -> None:
    campaign_id = _campaign(sqlite_engine)
    # The opens arrive one variant after the other, as an audience's do.
    for n in range(max(variant_opens)):
        for variant, opens in zip("AB", variant_opens, strict=True):
            if n < opens:
                assert _open(app_client, campaign_id, variant, f"{variant}-{n}") == 202

    assert _shown(app_client, campaign_id) == []
