"""The Campaign API in-process: a stub identity verifier and a stub Temporal client stand in
for Dex and the Temporal server, so a TestClient runs the real routes with no sockets."""

from pathlib import Path
from typing import Any

import yaml
from campaign_api.auth import User, _user_from_claims
from fastapi import HTTPException

DEX_CONFIG = Path(__file__).resolve().parents[2] / "platform/dex/config.yaml"
BAD_TOKEN = HTTPException(
    status_code=401, detail="not signed in", headers={"WWW-Authenticate": "Bearer"}
)


class StubVerifier:
    """Reads a demo user's email as the token and gives the user the real `groups` claim of
    platform/dex/config.yaml turns into; any other token is a 401, as with the real verifier."""

    def __init__(self) -> None:
        entries = yaml.safe_load(DEX_CONFIG.read_text())["staticPasswords"]
        self._claims = {
            e["email"]: {"sub": e["userID"], "email": e["email"], "groups": e["groups"]}
            for e in entries
        }

    def verify(self, token: str) -> User:
        if token not in self._claims:
            raise BAD_TOKEN
        return _user_from_claims(self._claims[token])


class StubWorkflowHandle:
    def __init__(self, workflow_id: str, signals: list[tuple[str, str, list[Any]]]) -> None:
        self._id = workflow_id
        self._signals = signals

    async def signal(self, name: str, *, args: list[Any] | None = None) -> None:
        self._signals.append((self._id, name, args or []))


class StubTemporal:
    """Records the workflows the API starts and the signals it sends (workflow id, signal
    name, args), and runs none."""

    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.signals: list[tuple[str, str, list[Any]]] = []

    async def start_workflow(self, name: str, **kwargs: object) -> None:
        self.started.append({"workflow": name, **kwargs})

    def get_workflow_handle(self, workflow_id: str) -> StubWorkflowHandle:
        return StubWorkflowHandle(workflow_id, self.signals)
