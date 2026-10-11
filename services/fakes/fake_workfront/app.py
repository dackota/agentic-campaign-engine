"""A fake Workfront shaped like its REST API: OAuth2 client credentials, projects, tasks, and
approvals, plus signed status webhooks to the Campaign API.

- `POST /oauth2/token` takes `grant_type=client_credentials` with the client id and secret
  (form body) and returns a bearer token.
- Every `/attask/api/v15.0/...` call needs that token; without it the fake answers 401.
- `POST /proj`, `POST /task`, and `POST /appr` are idempotent: a project and a task by their
  `externalID` (a repeat updates the task and returns the same one), an approval by its task.
- `GET /proj/search`, `/task/search`, and `/appr/search` filter by field; `GET /task/{id}`
  reads one task. A test can check from the outside what was published.
- `PUT /task/{id}` changes the task. A new `status` posts one signed status event, with the
  task's `externalID` as `campaignId`, to the webhook URL.
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
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

API_PREFIX = "/attask/api/v15.0"
TOKEN_TTL_SECONDS = 3600
WEBHOOK_TIMEOUT_SECONDS = 10
SIGNATURE_HEADER = "X-Workfront-Signature"
TIMESTAMP_HEADER = "X-Workfront-Timestamp"
CONFIG_ENV_PREFIX = "ACE_WORKFRONT_"
NEW_TASK_STATUS = "NEW"
PENDING_APPROVAL = "PENDING"
INVALID_TOKEN = {"error": {"class": "InvalidSessionException", "message": "Access token invalid"}}


@dataclass(frozen=True)
class WorkfrontConfig:
    client_id: str
    client_secret: str
    webhook_url: str
    webhook_secret: str

    def __post_init__(self) -> None:
        for name in ("client_id", "client_secret", "webhook_url", "webhook_secret"):
            if not getattr(self, name).strip():
                raise ValueError(f"fake Workfront needs a {name}")


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    externalID: str = Field(min_length=1, max_length=255)  # noqa: N815 (Workfront's name)


class NewTask(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    projectID: str | None = Field(default=None, max_length=64)  # noqa: N815
    externalID: str | None = Field(default=None, min_length=1, max_length=255)  # noqa: N815
    description: str = Field(default="", max_length=4000)


class TaskChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, min_length=1, max_length=40)


class NewApproval(BaseModel):
    taskID: str = Field(min_length=1, max_length=64)  # noqa: N815 (Workfront's name)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def _post_event(config: WorkfrontConfig, event: dict[str, Any]) -> None:
    """Post the status event, signed, to the webhook URL. A failure is logged, not raised."""
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
        log.warning("status webhook %s failed: %r", event["id"], exc)


def _copy(item: dict[str, Any]) -> dict[str, Any]:
    """A deep copy, so a reply never shares state the lock guards."""
    copied: dict[str, Any] = json.loads(json.dumps(item))
    return copied


def _new_id() -> str:
    return uuid.uuid4().hex


class _Store:
    """The fake's state, guarded by one lock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.tokens: dict[str, float] = {}
        self.projects: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}

    def task(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return task


def _matching(items: dict[str, dict[str, Any]], filters: Mapping[str, str | None]) -> list[Any]:
    wanted = {k: v for k, v in filters.items() if v is not None}
    return [_copy(i) for i in items.values() if all(i.get(k) == v for k, v in wanted.items())]


def create_app(config: WorkfrontConfig) -> FastAPI:
    store = _Store()
    app = FastAPI()

    def bearer(request: Request) -> None:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        with store.lock:
            expiry = store.tokens.get(token)
        if scheme.lower() != "bearer" or expiry is None or expiry < time.monotonic():
            raise HTTPException(status_code=401, detail=INVALID_TOKEN)

    authorized = [Depends(bearer)]

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _add_token_route(app, store, config)
    _add_project_routes(app, store, authorized)
    _add_task_routes(app, store, config, authorized)
    _add_approval_routes(app, store, authorized)
    return app


def _add_token_route(app: FastAPI, store: _Store, config: WorkfrontConfig) -> None:
    @app.post("/oauth2/token", response_model=None)
    async def token(request: Request) -> JSONResponse | dict[str, Any]:
        raw = (await request.body()).decode(errors="replace")
        fields = {k: v[0] for k, v in parse_qs(raw).items()}
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
        }


def _add_project_routes(app: FastAPI, store: _Store, authorized: list[Any]) -> None:
    @app.post(f"{API_PREFIX}/proj", dependencies=authorized)
    def create_project(body: NewProject) -> dict[str, Any]:
        with store.lock:
            found = _matching(store.projects, {"externalID": body.externalID})
            if found:
                return {"data": found[0]}
            project = {"ID": _new_id(), **body.model_dump()}
            store.projects[project["ID"]] = project
            return {"data": _copy(project)}

    @app.get(f"{API_PREFIX}/proj/search", dependencies=authorized)
    def search_projects(externalID: str | None = None) -> dict[str, Any]:  # noqa: N803
        with store.lock:
            return {"data": _matching(store.projects, {"externalID": externalID})}


def _add_task_routes(
    app: FastAPI, store: _Store, config: WorkfrontConfig, authorized: list[Any]
) -> None:
    @app.post(f"{API_PREFIX}/task", dependencies=authorized)
    def upsert_task(body: NewTask) -> dict[str, Any]:
        with store.lock:
            if body.projectID is not None and body.projectID not in store.projects:
                raise HTTPException(status_code=400, detail="project not found")
            found = (
                _matching(store.tasks, {"externalID": body.externalID}) if body.externalID else []
            )
            if found:
                task = store.tasks[found[0]["ID"]]
                task.update(body.model_dump(exclude_unset=True))
            else:
                task = {"ID": _new_id(), "status": NEW_TASK_STATUS, **body.model_dump()}
                store.tasks[task["ID"]] = task
            return {"data": _copy(task)}

    @app.get(f"{API_PREFIX}/task/search", dependencies=authorized)
    def search_tasks(
        externalID: str | None = None,  # noqa: N803
        projectID: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        with store.lock:
            return {
                "data": _matching(store.tasks, {"externalID": externalID, "projectID": projectID})
            }

    @app.get(API_PREFIX + "/task/{task_id}", dependencies=authorized)
    def get_task(task_id: str) -> dict[str, Any]:
        with store.lock:
            return {"data": _copy(store.task(task_id))}

    @app.put(API_PREFIX + "/task/{task_id}", dependencies=authorized)
    def change_task(task_id: str, body: TaskChange) -> dict[str, Any]:
        event = None
        with store.lock:
            task = store.task(task_id)
            if body.name is not None:
                task["name"] = body.name
            if body.status is not None and body.status != task["status"]:
                task["status"] = body.status
                event = {
                    "id": str(uuid.uuid4()),
                    "taskID": task["ID"],
                    "campaignId": task.get("externalID"),
                    "status": body.status,
                }
            reply = _copy(task)
        if event is not None:
            threading.Thread(target=_post_event, args=(config, event), daemon=True).start()
        return {"data": reply}


def _add_approval_routes(app: FastAPI, store: _Store, authorized: list[Any]) -> None:
    @app.post(f"{API_PREFIX}/appr", dependencies=authorized)
    def create_approval(body: NewApproval) -> dict[str, Any]:
        with store.lock:
            store.task(body.taskID)
            found = _matching(store.approvals, {"taskID": body.taskID})
            if found:
                return {"data": found[0]}
            approval = {"ID": _new_id(), "taskID": body.taskID, "status": PENDING_APPROVAL}
            store.approvals[approval["ID"]] = approval
            return {"data": _copy(approval)}

    @app.get(f"{API_PREFIX}/appr/search", dependencies=authorized)
    def search_approvals(taskID: str | None = None) -> dict[str, Any]:  # noqa: N803
        with store.lock:
            return {"data": _matching(store.approvals, {"taskID": taskID})}


def config_from_env(environ: Mapping[str, str]) -> WorkfrontConfig:
    """The fake's client and webhook settings, from `ACE_WORKFRONT_*` like the API's."""
    return from_env(WorkfrontConfig, environ, prefix=CONFIG_ENV_PREFIX)
