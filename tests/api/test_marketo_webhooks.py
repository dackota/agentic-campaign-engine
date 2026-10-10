"""Seam 1 at fast depth: the Campaign API's Marketo activity webhook. It takes a body only
when its HMAC signature is right and fresh, records each event id once, and answers any
malformed, oversized, or empty body with a 4xx, never a server error."""

import json
import random
import time
import uuid
from typing import Any

import httpx

from tests.api.helpers import (
    MARKETO_WEBHOOK_PATH,
    SENT,
    create,
    settle,
    signed_headers,
    until_status,
)
from tests.harness.stack import Stack

STALE_SECONDS = 3600
ACTIVITY_POLL_SECONDS = 15
ACTIVITY_POLL_INTERVAL_SECONDS = 0.2
PROPERTY_SEED = 34
PROPERTY_CASES = 150
OVERSIZED_BYTES = (256 * 1024, 2 * 1024 * 1024)


def event(campaign_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "open",
        "campaignId": campaign_id,
        "variant": "A",
        **overrides,
    }


def post(api: httpx.Client, body: bytes, headers: dict[str, str]) -> httpx.Response:
    return api.post(MARKETO_WEBHOOK_PATH, content=body, headers=headers)


def activity(api: httpx.Client, campaign_id: str) -> list[dict[str, Any]]:
    response = api.get(f"/campaigns/{campaign_id}/activity")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def test_signed_webhook_is_accepted_and_recorded(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    payload = event(campaign_id, type="click", variant="B")
    body = json.dumps(payload).encode()

    response = post(api, body, signed_headers(stack.marketo_webhook_secret, body))

    assert 200 <= response.status_code < 300, response.text
    [recorded] = activity(api, campaign_id)
    assert recorded["id"] == payload["id"]
    assert recorded["type"] == "click"
    assert recorded["variant"] == "B"


def test_bad_signature_is_401_and_not_recorded(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id)).encode()
    wrong_key = signed_headers("not-the-webhook-secret", body)
    tampered = signed_headers(stack.marketo_webhook_secret, body)
    tampered_body = json.dumps(event(campaign_id, type="click")).encode()

    assert post(api, body, wrong_key).status_code == 401
    assert post(api, tampered_body, tampered).status_code == 401
    assert post(api, body, {"Content-Type": "application/json"}).status_code == 401
    assert activity(api, campaign_id) == []


def test_stale_timestamp_is_401(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id)).encode()
    stale = signed_headers(stack.marketo_webhook_secret, body, int(time.time()) - STALE_SECONDS)

    assert post(api, body, stale).status_code == 401
    assert activity(api, campaign_id) == []


def test_replayed_id_is_409_and_recorded_once(stack: Stack, api: httpx.Client) -> None:
    campaign_id = create(api)["id"]
    body = json.dumps(event(campaign_id)).encode()
    first = post(api, body, signed_headers(stack.marketo_webhook_secret, body))
    assert 200 <= first.status_code < 300, first.text

    again = post(api, body, signed_headers(stack.marketo_webhook_secret, body))

    assert again.status_code == 409
    assert len(activity(api, campaign_id)) == 1


def test_fake_marketo_sends_signed_send_activity_after_approval(
    stack: Stack, api: httpx.Client, approver: httpx.Client
) -> None:
    campaign_id = create(api)["id"]
    settle(api, campaign_id)
    assert approver.post(f"/campaigns/{campaign_id}/approve").status_code == 202
    until_status(api, campaign_id, SENT)

    deadline = time.monotonic() + ACTIVITY_POLL_SECONDS
    sends: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        sends = [a for a in activity(api, campaign_id) if a["type"] == "send"]
        if len(sends) == 2:
            break
        time.sleep(ACTIVITY_POLL_INTERVAL_SECONDS)
    assert sorted(a["variant"] for a in sends) == ["A", "B"]


def _malformed_bodies(campaign_id: str) -> list[bytes]:
    """Empty, oversized, and malformed bodies: fixed hostile cases plus seeded random ones."""
    rng = random.Random(PROPERTY_SEED)
    good = event(campaign_id)
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
        json.dumps({**good, "type": None}).encode(),
        json.dumps({**good, "variant": "Z"}).encode(),
        json.dumps({**good, "campaignId": "not-a-uuid"}).encode(),
        json.dumps({**good, "campaignId": str(uuid.uuid4())}).encode(),
        json.dumps({k: v for k, v in good.items() if k != "id"}).encode(),
        json.dumps({**good, "id": "x" * 10_000}).encode(),
    ]
    fixed += [json.dumps({**good, "pad": "x" * size}).encode() for size in OVERSIZED_BYTES]
    fixed += [b"x" * size for size in OVERSIZED_BYTES]
    keys = list(good)
    junk_values: list[Any] = [None, 0, -1, 1e308, True, "", "\u0000", [], {}, "x" * 300, [1, 2]]
    generated: list[bytes] = []
    while len(fixed) + len(generated) < PROPERTY_CASES:
        roll = rng.random()
        if roll < 0.3:
            generated.append(rng.randbytes(rng.randint(1, 512)))
        elif roll < 0.6:
            mutated = dict(good)
            for key in rng.sample(keys, rng.randint(1, len(keys))):
                mutated[key] = rng.choice(junk_values)
            generated.append(json.dumps(mutated).encode())
        elif roll < 0.8:
            dropped = {k: v for k, v in good.items() if rng.random() < 0.5}
            dropped.pop(rng.choice(keys), None)
            generated.append(json.dumps(dropped).encode())
        else:
            text = json.dumps(good)
            cut = rng.randint(0, len(text) - 1)
            generated.append(text[:cut].encode())
    return fixed + generated


def test_malformed_oversized_or_empty_bodies_are_rejected_never_5xx(
    stack: Stack, api: httpx.Client
) -> None:
    campaign_id = create(api)["id"]

    for body in _malformed_bodies(campaign_id):
        signed = post(api, body, signed_headers(stack.marketo_webhook_secret, body))
        unsigned = post(api, body, {"Content-Type": "application/json"})

        for response in (signed, unsigned):
            assert 400 <= response.status_code < 500, (body[:80], response.status_code)
    assert activity(api, campaign_id) == []
