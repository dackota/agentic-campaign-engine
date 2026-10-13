"""The team's learnings: each called A/B winner, with the campaign it came from. Everyone in
the team reads them; only an approver deletes a bad one. Row-level security is the only team
filter."""

import uuid
from datetime import datetime
from typing import Any

from ace_engine import learnings, row_security
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from campaign_api.auth import Action, CurrentUser, authorize


class LearningOut(BaseModel):
    id: uuid.UUID
    text: str
    reason: str
    metrics: dict[str, Any]
    campaign_id: uuid.UUID
    # The first line of the source campaign's report, as the campaign list shows it.
    campaign_title: str
    created_at: datetime

    @classmethod
    def of(cls, found: learnings.Found) -> "LearningOut":
        learning = found.learning
        return cls(
            id=learning.id,
            text=learning.text,
            reason=learning.reason,
            metrics=learning.metrics,
            campaign_id=learning.campaign_id,
            campaign_title=found.campaign_title,
            created_at=learning.created_at,
        )


class DeletedOut(BaseModel):
    id: uuid.UUID


def register_learning_routes(app: FastAPI) -> None:
    @app.get("/learnings")
    async def list_learnings(request: Request, user: CurrentUser) -> list[LearningOut]:
        authorize(user, Action.READ)
        engine = row_security.for_team(request.app.state.engine, user.team)
        found = await run_in_threadpool(learnings.list_learnings, engine)
        return [LearningOut.of(f) for f in found]

    @app.delete("/learnings/{learning_id}")
    async def delete_learning(
        learning_id: uuid.UUID, request: Request, user: CurrentUser
    ) -> DeletedOut:
        """Remove a bad learning, so the agents stop reading it."""
        authorize(user, Action.APPROVE)
        engine = row_security.for_team(request.app.state.engine, user.team)
        if not await run_in_threadpool(learnings.remove, engine, learning_id):
            raise HTTPException(status_code=404, detail="learning not found")
        return DeletedOut(id=learning_id)
