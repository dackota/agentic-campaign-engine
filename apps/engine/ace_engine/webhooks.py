"""Webhook verifier: `verify(headers, body, secret)` checks the HMAC signature and the
timestamp of an incoming webhook. Replays by id are caught where the event is recorded.

The sender signs `"<timestamp>." + body` with HMAC-SHA256 and sends the hex digest as
`sha256=<hex>` in `X-Marketo-Signature`, with the Unix timestamp in `X-Marketo-Timestamp`.
"""

import hashlib
import hmac
import time
from collections.abc import Mapping

SIGNATURE_HEADER = "X-Marketo-Signature"
TIMESTAMP_HEADER = "X-Marketo-Timestamp"
SIGNATURE_PREFIX = "sha256="
# A signed body older or newer than this is a replay, even with a new id.
TOLERANCE_SECONDS = 300
MAX_TIMESTAMP_DIGITS = 12


class WebhookRejected(Exception):
    """The webhook is not from the sender, or not fresh. The message says which."""


def verify(
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    now: float | None = None,
    *,
    signature_header: str = SIGNATURE_HEADER,
    timestamp_header: str = TIMESTAMP_HEADER,
) -> None:
    """Return when the body is signed with `secret` and fresh; raise WebhookRejected if not.
    The header names default to Marketo's; another sender names its own."""
    stamp = headers.get(timestamp_header, "")
    signature = headers.get(signature_header, "")
    if not (stamp.isascii() and stamp.isdigit()) or len(stamp) > MAX_TIMESTAMP_DIGITS:
        raise WebhookRejected("missing or malformed timestamp")
    if not signature.startswith(SIGNATURE_PREFIX):
        raise WebhookRejected("missing or malformed signature")
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    given = signature.removeprefix(SIGNATURE_PREFIX)
    if not hmac.compare_digest(expected.hexdigest().encode(), given.encode()):
        raise WebhookRejected("signature does not match")
    current = time.time() if now is None else now
    if abs(current - int(stamp)) > TOLERANCE_SECONDS:
        raise WebhookRejected("timestamp is outside the replay window")
