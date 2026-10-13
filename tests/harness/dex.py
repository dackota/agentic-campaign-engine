"""Dex in Docker with the demo users from platform/dex/config.yaml, on a fixed local port.

The port is fixed (not Docker's pick) because the issuer URL is written into the config
before Dex starts, and the browser, the API, and the tokens must all agree on it.
"""

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from testcontainers.core.container import DockerContainer

DEX_IMAGE = (
    "ghcr.io/dexidp/dex:v2.46.0"
    "@sha256:933fcd3f523338c847b88ef84a7145fb2fcb7b9917f08418612afeaaa2001777"
)
CONFIG_PATH = Path(__file__).resolve().parents[2] / "platform/dex/config.yaml"
CONTAINER_CONFIG = "/etc/dex/config.yaml"
DEX_PORT_IN_CONTAINER = 5556
CLIENT_ID = "ace-web"
# Demo-only: the password every demo user in platform/dex/config.yaml has.
DEMO_PASSWORD = "demo-password"
TOKEN_SCOPE = "openid email profile groups"
TEAM_PREFIX = "team:"
ROLE_PREFIX = "role:"
READY_POLLS = 300
READY_POLL_SECONDS = 0.2
HTTP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class DemoUser:
    email: str
    team: str
    roles: frozenset[str]


def _load_config() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text())
    return config


def _demo_user(entry: dict[str, Any]) -> DemoUser:
    groups: list[str] = entry["groups"]
    teams = [g.removeprefix(TEAM_PREFIX) for g in groups if g.startswith(TEAM_PREFIX)]
    roles = frozenset(g.removeprefix(ROLE_PREFIX) for g in groups if g.startswith(ROLE_PREFIX))
    return DemoUser(email=entry["email"], team=teams[0], roles=roles)


DEMO_USERS: dict[str, DemoUser] = {
    entry["email"]: _demo_user(entry) for entry in _load_config()["staticPasswords"]
}


def render_config(issuer: str, web_origin: str) -> dict[str, Any]:
    """The checked-in config, pointed at this issuer and this web origin."""
    config = _load_config()
    clients = [{**client, "redirectURIs": [f"{web_origin}/"]} for client in config["staticClients"]]
    return {
        **config,
        "issuer": issuer,
        "web": {**config["web"], "allowedOrigins": [web_origin]},
        "staticClients": clients,
    }


class Dex:
    def __init__(self, port: int, web_origin: str, labels: dict[str, str] | None = None) -> None:
        self.port = port
        self.web_origin = web_origin
        self.labels = labels or {}
        self._container: DockerContainer | None = None
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self._tokens: dict[str, str] = {}

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self.port}/dex"

    def start(self) -> "Dex":
        self._dir = tempfile.TemporaryDirectory(prefix="ace-dex-")
        config_file = Path(self._dir.name) / "config.yaml"
        config_file.write_text(yaml.safe_dump(render_config(self.issuer, self.web_origin)))
        self._container = (
            DockerContainer(DEX_IMAGE)
            .with_bind_ports(DEX_PORT_IN_CONTAINER, self.port)
            .with_volume_mapping(str(config_file), CONTAINER_CONFIG, "ro")
            .with_command(f"dex serve {CONTAINER_CONFIG}")
            .with_kwargs(labels=self.labels)
        )
        try:
            self._container.start()
            self._wait_ready()
        except BaseException:
            self.stop()
            raise
        return self

    def stop(self) -> None:
        """Remove the container, also one that was created but failed to start. Safe to
        call twice."""
        container, self._container = self._container, None
        config_dir, self._dir = self._dir, None
        try:
            if container is not None:
                container.stop()
        finally:
            if config_dir is not None:
                config_dir.cleanup()

    def token(self, email: str) -> str:
        """A real access token for a demo user, from Dex's password grant."""
        if email not in self._tokens:
            response = httpx.post(
                f"{self.issuer}/token",
                data={
                    "grant_type": "password",
                    "username": email,
                    "password": DEMO_PASSWORD,
                    "client_id": CLIENT_ID,
                    "scope": TOKEN_SCOPE,
                },
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            assert response.status_code == 200, response.text
            self._tokens[email] = response.json()["access_token"]
        return self._tokens[email]

    def _wait_ready(self) -> None:
        url = f"{self.issuer}/.well-known/openid-configuration"
        for _ in range(READY_POLLS):
            try:
                if httpx.get(url, timeout=HTTP_TIMEOUT_SECONDS).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(READY_POLL_SECONDS)
        raise RuntimeError(f"Dex did not start at {self.issuer}")
