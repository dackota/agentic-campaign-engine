"""A fake Google OAuth and Docs API, enough to create a document and insert text.

- `POST /token` swaps a refresh token (`grant_type=refresh_token`, with the client id and
  secret) for an access token; anything else is a 400 or 401.
- `POST /v1/documents` creates a document from `{"title"}` and returns its `documentId`.
  It needs the access token.
- `POST /v1/documents/{id}:batchUpdate` applies `insertText` requests to the document.
- `GET /_documents` lists the documents with their text so a test can read them from the
  outside.
"""

import hmac
import secrets
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from ace_engine import telemetry
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi import Request as HttpRequest
from pydantic import BaseModel

ACCESS_TOKEN_LIFETIME_SECONDS = 3600
UNAUTHENTICATED = {"error": {"code": 401, "status": "UNAUTHENTICATED"}}


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    refresh_token: str

    def __post_init__(self) -> None:
        for name in ("client_id", "client_secret", "refresh_token"):
            if not getattr(self, name).strip():
                raise ValueError(f"fake Google needs a {name}")


class NewDocument(BaseModel):
    title: str


class Request(BaseModel):
    insertText: dict[str, Any] | None = None  # noqa: N815 (Google's name)


class BatchUpdate(BaseModel):
    requests: list[Request]


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _check_grant(body: bytes, config: GoogleConfig) -> None:
    """Refuse a token request that is not a refresh grant for the configured client."""
    # A form body, parsed by hand so the fake needs no multipart package.
    form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
    if form.get("grant_type", "") != "refresh_token":
        raise HTTPException(status_code=400, detail={"error": "unsupported_grant_type"})
    if not (
        _same(form.get("client_id", ""), config.client_id)
        and _same(form.get("client_secret", ""), config.client_secret)
        and _same(form.get("refresh_token", ""), config.refresh_token)
    ):
        raise HTTPException(status_code=401, detail={"error": "invalid_client"})


def create_app(config: GoogleConfig) -> FastAPI:
    app = FastAPI(title="fake-google")
    telemetry.instrument_app(app, "fake-google")
    access_tokens: set[str] = set()
    documents: dict[str, dict[str, str]] = {}
    lock = threading.Lock()

    def require_token(authorization: str | None = Header(default=None)) -> None:
        token = (authorization or "").removeprefix("Bearer ")
        with lock:
            if token not in access_tokens:
                raise HTTPException(status_code=401, detail=UNAUTHENTICATED)

    @app.post("/token")
    async def token(http: HttpRequest) -> dict[str, Any]:
        _check_grant(await http.body(), config)
        access = secrets.token_urlsafe(24)
        with lock:
            access_tokens.add(access)
        return {
            "access_token": access,
            "expires_in": ACCESS_TOKEN_LIFETIME_SECONDS,
            "token_type": "Bearer",
        }

    @app.post("/v1/documents", dependencies=[Depends(require_token)])
    def create_document(new: NewDocument) -> dict[str, str]:
        document_id = uuid.uuid4().hex
        with lock:
            documents[document_id] = {"id": document_id, "title": new.title, "text": ""}
        return {"documentId": document_id, "title": new.title}

    @app.post("/v1/documents/{document_id}:batchUpdate", dependencies=[Depends(require_token)])
    def batch_update(document_id: str, update: BatchUpdate) -> dict[str, str]:
        with lock:
            document = documents.get(document_id)
            if document is None:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            for request in update.requests:
                if request.insertText is not None:
                    document["text"] += str(request.insertText.get("text", ""))
        return {"documentId": document_id}

    @app.get("/_documents")
    def list_documents() -> list[dict[str, str]]:
        with lock:
            return list(documents.values())

    return app
