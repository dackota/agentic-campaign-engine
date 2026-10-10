"""Run the Campaign API: `python -m campaign_api`. Settings come from `ACE_*` variables."""

import os

import uvicorn
from ace_engine.env import settings_from_env
from fastapi import FastAPI

from campaign_api.main import create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def server_config(app: FastAPI, *, host: str = HOST, port: int = PORT) -> uvicorn.Config:
    """No access log: the event stream carries the bearer token in its query string
    (`?access_token=`, as EventSource cannot set a header), and a token must never be logged."""
    return uvicorn.Config(app, host=host, port=port, proxy_headers=True, access_log=False)


def main() -> None:
    app = create_app(settings_from_env(os.environ, is_api=True))
    uvicorn.Server(server_config(app)).run()


if __name__ == "__main__":
    main()
