"""Run the Campaign API: `python -m campaign_api`. Settings come from `ACE_*` variables."""

import os

import uvicorn
from ace_engine.env import settings_from_env

from campaign_api.main import create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def main() -> None:
    app = create_app(settings_from_env(os.environ, is_api=True))
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True)


if __name__ == "__main__":
    main()
