"""The webhook verifier both senders share (the Marketo activity webhook and the Workfront status
webhook): a body is taken only when its HMAC signature is right and its timestamp fresh. Each
sender names its own two headers, and each case runs for both."""

import json
import random

import pytest
from ace_engine import webhooks
from ace_engine.webhooks import (
    MARKETO_HEADERS,
    TOLERANCE_SECONDS,
    SignatureHeaders,
    WebhookRejected,
)
from campaign_api.webhook_routes import WORKFRONT_HEADERS

from tests.support.dag import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WORKFRONT_SIGNATURE_HEADER,
    WORKFRONT_TIMESTAMP_HEADER,
    signed_headers,
    workfront_signed_headers,
)

SECRET = "webhook-secret"
STAMP = 1_790_000_000
BODY = json.dumps({"id": "e1", "type": "open", "campaignId": "c", "variant": "A"}).encode()
SEED = 8
CASES = 300
SENDERS = {
    "marketo": (MARKETO_HEADERS, signed_headers, SIGNATURE_HEADER, TIMESTAMP_HEADER),
    "workfront": (
        WORKFRONT_HEADERS,
        workfront_signed_headers,
        WORKFRONT_SIGNATURE_HEADER,
        WORKFRONT_TIMESTAMP_HEADER,
    ),
}


@pytest.fixture(params=sorted(SENDERS))
def sender(request: pytest.FixtureRequest) -> str:
    name: str = request.param
    return name


def _headers(
    sender: str, body: bytes = BODY, secret: str = SECRET, stamp: int = STAMP
) -> dict[str, str]:
    return SENDERS[sender][1](secret, body, stamp)


def _verify(sender: str, headers: dict[str, str], body: bytes = BODY, now: float = STAMP) -> None:
    webhooks.verify(headers, body, SECRET, now=now, names=SENDERS[sender][0])


def test_a_body_signed_with_the_secret_and_fresh_is_accepted(sender: str) -> None:
    _verify(sender, _headers(sender))


def test_a_wrong_key_or_a_tampered_body_is_rejected(sender: str) -> None:
    wrong_key = _headers(sender, secret="not-the-webhook-secret")
    signed_for_another_body = _headers(sender, body=b'{"id": "other"}')

    with pytest.raises(WebhookRejected, match="signature does not match"):
        _verify(sender, wrong_key)
    with pytest.raises(WebhookRejected, match="signature does not match"):
        _verify(sender, signed_for_another_body)


def test_a_body_with_no_signature_headers_is_rejected(sender: str) -> None:
    with pytest.raises(WebhookRejected, match="timestamp"):
        _verify(sender, {"Content-Type": "application/json"})


@pytest.mark.parametrize("stamp", ["", "abc", "12ab", "-5", "1.5", " 1", "٣", "9" * 13])
def test_a_timestamp_that_is_not_a_short_ascii_number_is_rejected(sender: str, stamp: str) -> None:
    headers = {**_headers(sender), SENDERS[sender][3]: stamp}

    with pytest.raises(WebhookRejected, match="malformed timestamp"):
        _verify(sender, headers)


@pytest.mark.parametrize("signature", ["", "deadbeef", "md5=abc", "SHA256=abc"])
def test_a_signature_without_the_sha256_prefix_is_rejected(sender: str, signature: str) -> None:
    headers = {**_headers(sender), SENDERS[sender][2]: signature}

    with pytest.raises(WebhookRejected, match="malformed signature"):
        _verify(sender, headers)


@pytest.mark.parametrize("offset", [-TOLERANCE_SECONDS, 0, TOLERANCE_SECONDS])
def test_a_timestamp_within_the_window_is_accepted(sender: str, offset: int) -> None:
    _verify(sender, _headers(sender), now=STAMP + offset)


@pytest.mark.parametrize("offset", [-TOLERANCE_SECONDS - 1, TOLERANCE_SECONDS + 1, 3600])
def test_a_stale_or_future_timestamp_is_rejected_even_when_signed(sender: str, offset: int) -> None:
    with pytest.raises(WebhookRejected, match="replay window"):
        _verify(sender, _headers(sender), now=STAMP + offset)


def test_a_body_signed_for_the_other_sender_is_rejected() -> None:
    marketo = signed_headers(SECRET, BODY, STAMP)
    workfront = workfront_signed_headers(SECRET, BODY, STAMP)

    with pytest.raises(WebhookRejected):
        webhooks.verify(marketo, BODY, SECRET, now=STAMP, names=WORKFRONT_HEADERS)
    with pytest.raises(WebhookRejected):
        webhooks.verify(workfront, BODY, SECRET, now=STAMP, names=MARKETO_HEADERS)


def test_whatever_the_headers_say_the_verifier_rejects_or_accepts_but_never_crashes() -> None:
    rng = random.Random(SEED)
    names = SignatureHeaders("X-Sig", "X-Time")
    junk = ["", "0", "sha256=", "sha256=zz", "\u0000", "x" * 500, "9" * 40, "١٢٣", " ", "-1"]

    for _ in range(CASES):
        headers = {h: rng.choice(junk) for h in ("X-Sig", "X-Time") if rng.random() < 0.8}
        body = rng.randbytes(rng.randint(0, 64))

        try:
            webhooks.verify(headers, body, SECRET, now=STAMP, names=names)
        except WebhookRejected:
            continue
        pytest.fail(f"accepted a forged webhook: {headers!r}")
