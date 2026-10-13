"""Seam 1 at fast depth: a called A/B winner becomes a learning. The team reads it at
GET /learnings and through the learnings search MCP tool; another team sees none of it, as
row-level security is the only team filter; only an approver deletes one."""

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from ace_engine import learnings
from ace_engine.db import EMBEDDING_DIMENSIONS
from ace_mcp import learnings as learnings_mcp
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from tests.api.conftest import SignIn
from tests.api.helpers import DAY_SPEED, REPORT, send_campaign
from tests.harness.stack import Stack

SEED = 1  # a seed whose audience opens variant A far more than B
SETTLE_SECONDS = 30
POLL_SECONDS = 0.2
TEAM_A, TEAM_B = "demand-gen", "product-marketing"
TEAM_B_OWNER = "pm-owner@demo.example"
TEAM_B_APPROVER = "pm-approver@demo.example"


def learnings_of(client: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    response = client.get("/learnings")
    assert response.status_code == 200, response.text
    return [item for item in response.json() if item["campaign_id"] == campaign_id]


def learned(api: httpx.Client, approver: httpx.Client, stack: Stack) -> dict[str, Any]:
    """Send a campaign, let the simulated audience call a winner, and return its learning."""
    stack.marketo_audience(seed=SEED, time_speed=DAY_SPEED)
    campaign_id = send_campaign(api, approver)
    deadline = time.monotonic() + SETTLE_SECONDS
    found = learnings_of(api, campaign_id)
    while not found and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        found = learnings_of(api, campaign_id)
    assert len(found) == 1, found
    return found[0]


@pytest.fixture
def database(stack: Stack) -> Iterator[Engine]:
    engine = create_engine(stack.database_url)
    yield engine
    engine.dispose()


def mcp_search(database: Engine, team: str, query: str) -> list[dict[str, Any]]:
    mcp = TestClient(learnings_mcp.create_app(database, team, learnings.stand_in_embedding))
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


def test_a_called_winner_creates_one_learning_with_its_text_reason_metrics_and_embedding(
    stack: Stack, api: httpx.Client, approver: httpx.Client, database: Engine
) -> None:
    learning = learned(api, approver, stack)

    campaign = api.get(f"/campaigns/{learning['campaign_id']}").json()
    winner = campaign["ab_result"]["winner"]
    winning_email = campaign["draft"] if winner == "A" else campaign["variant_b"]
    assert winning_email["subject"] in learning["text"]
    assert learning["reason"].startswith(f"Variant {winner} won")
    assert learning["campaign_title"] == REPORT.split("\n", 1)[0]
    assert learning["metrics"]["winner"] == winner
    assert learning["metrics"]["confidence"] >= 0.95
    assert set(learning["metrics"]["engagement"]) == {"A", "B"}
    with database.connect() as conn:
        dims = conn.execute(
            text("SELECT vector_dims(embedding) FROM learnings WHERE id = :id"),
            {"id": uuid.UUID(learning["id"])},
        ).scalar_one()
    assert dims == EMBEDDING_DIMENSIONS


def test_another_team_neither_reads_nor_deletes_the_learning(
    stack: Stack, api: httpx.Client, approver: httpx.Client, sign_in: SignIn
) -> None:
    learning = learned(api, approver, stack)
    team_b, team_b_approver = sign_in(TEAM_B_OWNER), sign_in(TEAM_B_APPROVER)

    assert learnings_of(team_b, learning["campaign_id"]) == []
    assert team_b_approver.delete(f"/learnings/{learning['id']}").status_code == 404
    assert len(learnings_of(api, learning["campaign_id"])) == 1


def test_the_search_mcp_tool_returns_the_learning_for_a_matching_query_and_only_to_its_team(
    stack: Stack, api: httpx.Client, approver: httpx.Client, database: Engine
) -> None:
    learning = learned(api, approver, stack)

    found = mcp_search(database, TEAM_A, learning["text"])
    other_team = mcp_search(database, TEAM_B, learning["text"])

    assert found[0]["id"] == learning["id"]
    assert found[0]["text"] == learning["text"]
    assert found[0]["reason"] == learning["reason"]
    assert all(item["campaign_id"] != learning["campaign_id"] for item in other_team)


def test_an_approver_deletes_a_learning_and_an_owner_cannot(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    learning = learned(api, approver, stack)

    assert api.delete(f"/learnings/{learning['id']}").status_code == 403
    deleted = approver.delete(f"/learnings/{learning['id']}")

    assert deleted.status_code == 200, deleted.text
    assert learnings_of(api, learning["campaign_id"]) == []
    assert approver.delete(f"/learnings/{learning['id']}").status_code == 404
