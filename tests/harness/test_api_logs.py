"""The API process logs no request query string: the browser's event stream sends its
bearer token as `?access_token=`, and a token must never land in a log."""

import importlib
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

TOKEN = "sentinel-token-3f9a"
START_POLLS = 100
POLL_SECONDS = 0.05


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_api_server_does_not_log_query_strings(capfd: pytest.CaptureFixture[str]) -> None:
    entry = importlib.import_module("campaign_api.__main__")
    assert hasattr(entry, "server_config"), "the API entrypoint has no server_config"
    app = FastAPI()

    @app.get("/campaigns/x/events")
    def events() -> dict[str, str]:
        return {"ok": "yes"}

    port = _free_port()
    config: uvicorn.Config = entry.server_config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(START_POLLS):
            if server.started:
                break
            time.sleep(POLL_SECONDS)
        assert server.started
        reply = httpx.get(f"http://127.0.0.1:{port}/campaigns/x/events?access_token={TOKEN}")
        assert reply.status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    out, err = capfd.readouterr()
    assert TOKEN not in out + err
