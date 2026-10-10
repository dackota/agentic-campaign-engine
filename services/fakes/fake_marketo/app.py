"""A fake Marketo shaped like the real REST API: OAuth2 client credentials, programs, and
A/B sends, plus signed activity webhooks to the Campaign API.

- `POST /identity/oauth/token` takes `grant_type=client_credentials` with the client id and
  secret (form body or query, as Marketo allows) and returns a bearer token.
- Every `/rest/...` call needs that token; without it the fake answers 401.
- `POST /rest/asset/v1/programs.json` creates a program. It is idempotent per
  `externalId`: a repeat returns the same program.
- `POST /rest/asset/v1/program/{id}/abSend.json` sends the variants once per program; a
  repeat returns the same send. The first send posts one signed `send` activity per
  variant to the webhook URL.
- `GET /rest/asset/v1/programs.json[?externalId=]` shows programs with their sends, so a
  test can check from the outside what was published.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

import httpx
from ace_engine.env import from_env
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

RECEIPT_HEX_LENGTH = 12
TOKEN_TTL_SECONDS = 3600
WEBHOOK_TIMEOUT_SECONDS = 10
SIGNATURE_HEADER = "X-Marketo-Signature"
TIMESTAMP_HEADER = "X-Marketo-Timestamp"
MIN_AB_VARIANTS = 2
MAX_AB_VARIANTS = 2
CONFIG_ENV_PREFIX = "ACE_MARKETO_"
INVALID_TOKEN = {"success": False, "errors": [{"code": "601", "message": "Access token invalid"}]}


@dataclass(frozen=True)
class MarketoConfig:
    client_id: str
    client_secret: str
    webhook_url: str
    webhook_secret: str

    def __post_init__(self) -> None:
        for name in ("client_id", "client_secret", "webhook_url", "webhook_secret"):
            if not getattr(self, name).strip():
                raise ValueError(f"fake Marketo needs a {name}")


class Fault(BaseModel):
    malformed_reply: bool = False
    drop_next_send_reply: bool = False


class NewProgram(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    externalId: str = Field(min_length=1, max_length=255)  # noqa: N815 (Marketo's name)


class Variant(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    subject: str
    preheader: str
    body: str
    callToAction: str  # noqa: N815 (Marketo's name)


class AbSend(BaseModel):
    variants: list[Variant] = Field(min_length=MIN_AB_VARIANTS, max_length=MAX_AB_VARIANTS)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def _post_activity(config: MarketoConfig, events: list[dict[str, Any]]) -> None:
    """Post each activity, signed, to the webhook URL. Failures are logged, not raised."""
    for event in events:
        body = json.dumps(event).encode()
        stamp = str(int(time.time()))
        headers = {
            TIMESTAMP_HEADER: stamp,
            SIGNATURE_HEADER: sign(config.webhook_secret, stamp, body),
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                config.webhook_url, content=body, headers=headers, timeout=WEBHOOK_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("activity webhook %s failed: %r", event["id"], exc)


def _copy(program: dict[str, Any]) -> dict[str, Any]:
    """A deep copy, so a reply never shares state the lock guards."""
    copied: dict[str, Any] = json.loads(json.dumps(program))
    return copied


class _Store:
    """The fake's state, guarded by one lock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.tokens: dict[str, float] = {}
        self.programs: dict[int, dict[str, Any]] = {}
        self.by_external_id: dict[str, int] = {}
        self.fault = Fault()

    def program(self, program_id: int) -> dict[str, Any]:
        program = self.programs.get(program_id)
        if program is None:
            raise HTTPException(status_code=404, detail="program not found")
        return program


async def _credentials(request: Request) -> dict[str, str]:
    """OAuth2 token request fields from the form body and the query, as Marketo allows."""
    fields = {k: v[0] for k, v in parse_qs((await request.body()).decode(errors="replace")).items()}
    return {**dict(request.query_params), **fields}


def create_app(config: MarketoConfig) -> FastAPI:
    store = _Store()
    app = FastAPI()

    def bearer(request: Request) -> None:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        with store.lock:
            expiry = store.tokens.get(token)
        if scheme.lower() != "bearer" or expiry is None or expiry < time.monotonic():
            raise HTTPException(status_code=401, detail=INVALID_TOKEN)

    authorized = [Depends(bearer)]
    _add_ops_routes(app, store)
    _add_token_route(app, store, config)
    _add_program_routes(app, store, authorized)
    _add_send_route(app, store, config, authorized)
    return app


def _add_ops_routes(app: FastAPI, store: _Store) -> None:
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/_fault", status_code=204)
    def set_fault(body: Fault) -> Response:
        """Test hook: break the next send replies on purpose."""
        with store.lock:
            store.fault = body
        return Response(status_code=204)


def _add_token_route(app: FastAPI, store: _Store, config: MarketoConfig) -> None:
    @app.post("/identity/oauth/token", response_model=None)
    async def token(request: Request) -> JSONResponse | dict[str, Any]:
        fields = await _credentials(request)
        if fields.get("grant_type") != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        is_client = hmac.compare_digest(fields.get("client_id", ""), config.client_id)
        is_secret = hmac.compare_digest(fields.get("client_secret", ""), config.client_secret)
        if not (is_client and is_secret):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        access_token = secrets.token_urlsafe(24)
        with store.lock:
            store.tokens[access_token] = time.monotonic() + TOKEN_TTL_SECONDS
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "scope": config.client_id,
        }


def _add_program_routes(app: FastAPI, store: _Store, authorized: list[Any]) -> None:
    @app.post("/rest/asset/v1/programs.json", dependencies=authorized)
    def create_program(body: NewProgram) -> dict[str, Any]:
        with store.lock:
            program_id = store.by_external_id.get(body.externalId)
            if program_id is None:
                program_id = len(store.programs) + 1
                store.programs[program_id] = {
                    "id": program_id,
                    "name": body.name,
                    "externalId": body.externalId,
                    "sends": [],
                }
                store.by_external_id[body.externalId] = program_id
            program = store.programs[program_id]
            return {"success": True, "result": [_copy(program)]}

    @app.get("/rest/asset/v1/programs.json", dependencies=authorized)
    def list_programs(externalId: str | None = None) -> dict[str, Any]:  # noqa: N803
        with store.lock:
            found = [
                _copy(p)
                for p in store.programs.values()
                if externalId is None or p["externalId"] == externalId
            ]
        return {"success": True, "result": found}

    @app.get("/rest/asset/v1/program/{program_id}.json", dependencies=authorized)
    def get_program(program_id: int) -> dict[str, Any]:
        with store.lock:
            return {"success": True, "result": [_copy(store.program(program_id))]}


def _record_send(store: _Store, program_id: int, body: AbSend) -> tuple[dict[str, Any], bool]:
    """The program's one send, made now if it has none; and whether it was made now.
    The caller holds the lock."""
    program = store.program(program_id)
    is_new = not program["sends"]
    if is_new:
        program["sends"].append(
            {
                "id": str(uuid.uuid4()),
                "receiptId": f"fake-marketo-{uuid.uuid4().hex[:RECEIPT_HEX_LENGTH]}",
                "status": "sent",
                "variants": [v.model_dump() for v in body.variants],
            }
        )
    return program, is_new


def _send_events(program: dict[str, Any], labels: list[str]) -> list[dict[str, Any]]:
    send_id = program["sends"][0]["id"]
    return [
        {
            "id": f"{send_id}-{label}",
            "type": "send",
            "campaignId": program["externalId"],
            "variant": label,
        }
        for label in labels
    ]


def _add_send_route(
    app: FastAPI, store: _Store, config: MarketoConfig, authorized: list[Any]
) -> None:
    @app.post(
        "/rest/asset/v1/program/{program_id}/abSend.json",
        dependencies=authorized,
        response_model=None,
    )
    def ab_send(program_id: int, body: AbSend) -> JSONResponse | dict[str, Any]:
        labels = [v.label for v in body.variants]
        if len(set(labels)) != len(labels):
            raise HTTPException(status_code=400, detail="variant labels must differ")
        with store.lock:
            fault = store.fault
            if fault.malformed_reply:
                store.program(program_id)
                return {"success": True, "result": []}
            program, is_new = _record_send(store, program_id, body)
            send = _copy(program["sends"][0])
            events = _send_events(program, labels) if is_new else []
            if fault.drop_next_send_reply:
                store.fault = fault.model_copy(update={"drop_next_send_reply": False})
        if events:
            threading.Thread(target=_post_activity, args=(config, events), daemon=True).start()
        if fault.drop_next_send_reply:
            return JSONResponse({"success": False, "errors": [{"code": "604"}]}, status_code=503)
        return {
            "success": True,
            "result": [{"id": send["id"], "receiptId": send["receiptId"], "status": "sent"}],
        }


def config_from_env(environ: Mapping[str, str]) -> MarketoConfig:
    """The fake's client and webhook settings, from `ACE_MARKETO_*` like the API's."""
    return from_env(MarketoConfig, environ, prefix=CONFIG_ENV_PREFIX)
