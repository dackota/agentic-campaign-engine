"""Workflow routes: save a new version of a workflow DAG, read one back.

A bad workflow gets a 422 whose detail lists named rejections, each with a
plain-language message. Saved versions are never edited, so a run can pin one."""

import json
from dataclasses import asdict
from typing import Annotated, Any

from ace_engine import db
from ace_engine.workflow_spec import Rejection, validate
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from campaign_api.auth import Action, CurrentUser, authorize

NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
MAX_WORKFLOW_BYTES = 256_000
SAVE_ATTEMPTS = 3
WorkflowName = Annotated[str, Path(pattern=NAME_PATTERN)]


class WorkflowVersionOut(BaseModel):
    workflow: str
    version: int
    dag: dict[str, Any]


class RejectionOut(BaseModel):
    rule: str
    message: str


class ValidationOut(BaseModel):
    rejections: list[RejectionOut]


class VersionSummary(BaseModel):
    version: int


def _reject(*rejections: Rejection) -> HTTPException:
    return HTTPException(status_code=422, detail=[asdict(r) for r in rejections])


def _parse(raw: bytes) -> object:
    if len(raw) > MAX_WORKFLOW_BYTES:
        raise _reject(Rejection("too_large", f"the workflow is over {MAX_WORKFLOW_BYTES} bytes"))
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise _reject(Rejection("not_json", "the workflow is not valid JSON")) from None


def _save(engine: Engine, name: str, dag: dict[str, Any]) -> int:
    """Add the next version of `name`; a racing save of the same name retries."""
    for _ in range(SAVE_ATTEMPTS):
        try:
            with Session(engine) as session, session.begin():
                latest = session.scalar(
                    select(func.max(db.WorkflowVersion.version)).where(
                        db.WorkflowVersion.name == name
                    )
                )
                version = (latest or 0) + 1
                session.add(db.WorkflowVersion(name=name, version=version, dag=dag))
            return version
        except IntegrityError:
            continue
    raise HTTPException(status_code=409, detail="the workflow changed while saving; try again")


def _versions(engine: Engine, name: str) -> list[int]:
    with Session(engine) as session:
        query = (
            select(db.WorkflowVersion.version)
            .where(db.WorkflowVersion.name == name)
            .order_by(db.WorkflowVersion.version.desc())
        )
        return list(session.scalars(query))


def _find(engine: Engine, name: str, version: int | None) -> db.WorkflowVersion | None:
    """One version of `name`, or its latest version when `version` is None."""
    with Session(engine) as session:
        query = select(db.WorkflowVersion).where(db.WorkflowVersion.name == name)
        if version is not None:
            query = query.where(db.WorkflowVersion.version == version)
        return session.scalars(query.order_by(db.WorkflowVersion.version.desc())).first()


async def latest_version(engine: Engine, name: str) -> db.WorkflowVersion | None:
    return await run_in_threadpool(_find, engine, name, None)


def register_workflow_routes(app: FastAPI) -> None:
    @app.post("/workflows/validate")
    async def validate_workflow(request: Request, user: CurrentUser) -> ValidationOut:
        """The same checks as a save, without saving: the builder shows these before save."""
        authorize(user, Action.CREATE)
        try:
            instance = _parse(await request.body())
        except HTTPException as exc:
            detail = exc.detail
            assert isinstance(detail, list)
            return ValidationOut(rejections=[RejectionOut(**r) for r in detail])
        return ValidationOut(rejections=[RejectionOut(**asdict(r)) for r in validate(instance)])

    @app.get("/workflows/{name}/versions")
    async def list_workflow_versions(
        name: WorkflowName, request: Request, user: CurrentUser
    ) -> list[VersionSummary]:
        authorize(user, Action.READ)
        found = await run_in_threadpool(_versions, request.app.state.engine, name)
        return [VersionSummary(version=v) for v in found]

    @app.post("/workflows/{name}/versions", status_code=201)
    async def save_workflow_version(
        name: WorkflowName, request: Request, user: CurrentUser
    ) -> WorkflowVersionOut:
        authorize(user, Action.CREATE)
        instance = _parse(await request.body())
        rejections = validate(instance)
        if rejections:
            raise _reject(*rejections)
        assert isinstance(instance, dict)
        version = await run_in_threadpool(_save, request.app.state.engine, name, instance)
        return WorkflowVersionOut(workflow=name, version=version, dag=instance)

    @app.get("/workflows/{name}/versions/{version}")
    async def get_workflow_version(
        name: WorkflowName, version: int, request: Request, user: CurrentUser
    ) -> WorkflowVersionOut:
        authorize(user, Action.READ)
        found = await run_in_threadpool(_find, request.app.state.engine, name, version)
        if found is None:
            raise HTTPException(status_code=404, detail="workflow version not found")
        return WorkflowVersionOut(workflow=found.name, version=found.version, dag=found.dag)
