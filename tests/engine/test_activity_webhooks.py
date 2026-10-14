"""The Campaign API's two signed webhooks, in process on SQLite: the Marketo activity webhook and
the Workfront task-status webhook. Each takes a body only when its signature is right and fresh,
records each event id once, and answers any malformed, oversized, or empty body with a 4xx,
never a server error. How the signature is checked is in test_webhook_verify.py."""

import json
import random
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from ace_engine.settings import Settings
from campaign_api.webhook_routes import MAX_WEBHOOK_BYTES
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.support.campaigns import add_campaign
from tests.support.dag import OWNER, signed_headers, workfront_signed_headers
from tests.support.settings import unit_settings

MARKETO_SECRET = "marketo-webhook-secret"
WORKFRONT_SECRET = "workfront-webhook-secret"
MARKETO_PATH = "/webhooks/marketo"
WORKFRONT_PATH = "/webhooks/workfront"
STALE_SECONDS = 3600
SEED = 34
CASES = 150
OVERSIZED_BYTES = (256 * 1024, 2 * 1024 * 1024)
SignedHeaders = Callable[[str, bytes, int | None], dict[str, str]]


@pytest.fixture
def app_settings() -> Settings:
    """Replaces the shared fixture: the Workfront route is on, as when the fake is set up."""
    return unit_settings(
        workfront_url="http://workfront.test",
        workfront_client_id="workfront-id",
        workfront_client_secret="workfront-secret",
        workfront_webhook_secret=WORKFRONT_SECRET,
    )


class Sender:
    """One signed webhook: its path, secret, signer, and a well-formed event."""

    def __init__(
        self, path: str, secret: str, sign: SignedHeaders, event: Callable[..., dict[str, Any]]
    ) -> None:
        self.path, self.secret, self.sign, self.event = path, secret, sign, event


def _marketo_event(campaign_id: str, **overrides: object) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "open",
        "campaignId": campaign_id,
        "variant": "A",
        **overrides,
    }


def _workfront_event(campaign_id: str, **overrides: object) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "taskID": "task-1",
        "campaignId": campaign_id,
        "status": "INP",
        **overrides,
    }


MARKETO = Sender(MARKETO_PATH, MARKETO_SECRET, signed_headers, _marketo_event)
WORKFRONT = Sender(WORKFRONT_PATH, WORKFRONT_SECRET, workfront_signed_headers, _workfront_event)


@pytest.fixture(params=[MARKETO, WORKFRONT], ids=["marketo", "workfront"])
def sender(request: pytest.FixtureRequest) -> Sender:
    chosen: Sender = request.param
    return chosen


def _as_owner() -> dict[str, str]:
    return {"Authorization": f"Bearer {OWNER}"}


def _recorded(client: TestClient, sender: Sender, campaign_id: str) -> list[Any]:
    """What the campaign shows of this sender's events."""
    if sender is MARKETO:
        response = client.get(f"/campaigns/{campaign_id}/activity", headers=_as_owner())
        assert response.status_code == 200, response.text
        events: list[Any] = response.json()
        return events
    shown = client.get(f"/campaigns/{campaign_id}", headers=_as_owner()).json()["task_status"]
    return [] if shown is None else [shown]


def _post(client: TestClient, sender: Sender, body: bytes, timestamp: int | None = None) -> int:
    response = client.post(
        sender.path, content=body, headers=sender.sign(sender.secret, body, timestamp)
    )
    status: int = response.status_code
    return status


def test_a_signed_marketo_webhook_is_accepted_and_recorded(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    payload = _marketo_event(campaign_id, type="click", variant="B")

    assert _post(app_client, MARKETO, json.dumps(payload).encode()) == 202

    [recorded] = _recorded(app_client, MARKETO, campaign_id)
    assert (recorded["id"], recorded["type"], recorded["variant"]) == (payload["id"], "click", "B")


def test_a_signed_workfront_webhook_shows_its_status_on_the_campaign(
    app_client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    body = json.dumps(_workfront_event(campaign_id, status="CLS")).encode()

    assert _post(app_client, WORKFRONT, body) == 202

    assert _recorded(app_client, WORKFRONT, campaign_id) == ["CLS"]


def test_a_wrong_key_a_tampered_body_or_no_signature_is_401_and_not_recorded(
    app_client: TestClient, sqlite_engine: Engine, sender: Sender
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    body = json.dumps(sender.event(campaign_id)).encode()
    other_body = json.dumps(sender.event(campaign_id, status="CLS", type="click")).encode()
    wrong_key = sender.sign("not-the-webhook-secret", body, None)
    tampered = sender.sign(sender.secret, body, None)

    assert app_client.post(sender.path, content=body, headers=wrong_key).status_code == 401
    assert app_client.post(sender.path, content=other_body, headers=tampered).status_code == 401
    assert app_client.post(sender.path, content=body).status_code == 401
    assert _recorded(app_client, sender, campaign_id) == []


def test_a_stale_timestamp_is_401_and_not_recorded(
    app_client: TestClient, sqlite_engine: Engine, sender: Sender
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    body = json.dumps(sender.event(campaign_id)).encode()

    assert _post(app_client, sender, body, int(time.time()) - STALE_SECONDS) == 401
    assert _recorded(app_client, sender, campaign_id) == []


def test_a_replayed_event_id_is_409_and_recorded_once(
    app_client: TestClient, sqlite_engine: Engine, sender: Sender
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    body = json.dumps(sender.event(campaign_id)).encode()
    assert _post(app_client, sender, body) == 202

    assert _post(app_client, sender, body) == 409

    assert len(_recorded(app_client, sender, campaign_id)) == 1


def test_an_event_for_a_campaign_that_does_not_exist_is_refused(
    app_client: TestClient, sender: Sender
) -> None:
    body = json.dumps(sender.event(str(uuid.uuid4()))).encode()

    assert _post(app_client, sender, body) == 422


def _hostile_bodies(good: dict[str, Any]) -> list[bytes]:
    """Empty, oversized, and malformed bodies: fixed hostile cases plus seeded random ones."""
    rng = random.Random(SEED)
    keys = list(good)
    fixed: list[bytes] = [
        b"",
        b" ",
        b"null",
        b"[]",
        b"{}",
        b"0",
        b'"a string"',
        b"{not json",
        b"\xff\xfe\x00garbage",
        b"[" * 5000 + b"]" * 5000,
        json.dumps({**good, "id": ""}).encode(),
        json.dumps({**good, "id": 7}).encode(),
        json.dumps({**good, "type": None, "status": None}).encode(),
        json.dumps({**good, "variant": "Z", "status": "x" * 500}).encode(),
        json.dumps({**good, "campaignId": "not-a-uuid"}).encode(),
        json.dumps({**good, "campaignId": str(uuid.uuid4())}).encode(),
        json.dumps({k: v for k, v in good.items() if k != "id"}).encode(),
        json.dumps({**good, "id": "x" * 10_000}).encode(),
    ]
    fixed += [json.dumps({**good, "pad": "x" * size}).encode() for size in OVERSIZED_BYTES]
    fixed += [b"x" * size for size in OVERSIZED_BYTES]
    junk: list[Any] = [None, 0, -1, 1e308, True, "", "\u0000", [], {}, "x" * 300, [1, 2]]
    generated: list[bytes] = []
    while len(fixed) + len(generated) < CASES:
        roll = rng.random()
        if roll < 0.3:
            generated.append(rng.randbytes(rng.randint(1, 512)))
        elif roll < 0.6:
            mutated = dict(good)
            for key in rng.sample(keys, rng.randint(1, len(keys))):
                mutated[key] = rng.choice(junk)
            generated.append(json.dumps(mutated).encode())
        elif roll < 0.8:
            dropped = {k: v for k, v in good.items() if rng.random() < 0.5}
            dropped.pop(rng.choice(keys), None)
            generated.append(json.dumps(dropped).encode())
        else:
            text = json.dumps(good)
            generated.append(text[: rng.randint(0, len(text) - 1)].encode())
    return fixed + generated


def test_malformed_oversized_or_empty_bodies_are_rejected_never_5xx(
    app_client: TestClient, sqlite_engine: Engine, sender: Sender
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))

    for body in _hostile_bodies(sender.event(campaign_id)):
        signed = _post(app_client, sender, body)
        unsigned = app_client.post(sender.path, content=body).status_code

        for status in (signed, unsigned):
            assert 400 <= status < 500, (body[:80], status)
    assert _recorded(app_client, sender, campaign_id) == []


@pytest.mark.parametrize("size", [MAX_WEBHOOK_BYTES + 1, 2 * 1024 * 1024])
def test_a_body_over_the_cap_is_413_even_when_signed(
    app_client: TestClient, sender: Sender, size: int
) -> None:
    assert _post(app_client, sender, b"x" * size) == 413


def test_a_body_over_the_cap_that_declares_no_length_is_413_as_it_streams_in(
    app_client: TestClient, sender: Sender
) -> None:
    chunk = b"x" * 16_384

    def chunks() -> Iterator[bytes]:
        for _ in range(MAX_WEBHOOK_BYTES // len(chunk) + 2):
            yield chunk

    response = app_client.post(sender.path, content=chunks())

    assert response.status_code == 413
