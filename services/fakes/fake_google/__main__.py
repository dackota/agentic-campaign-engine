"""Run the fake Google: `python -m fake_google`. Config comes from `ACE_GOOGLE_*`."""

import os

import uvicorn

from fake_google.app import GoogleConfig, create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def main() -> None:
    config = GoogleConfig(
        client_id=os.environ.get("ACE_GOOGLE_CLIENT_ID", ""),
        client_secret=os.environ.get("ACE_GOOGLE_CLIENT_SECRET", ""),
        refresh_token=os.environ.get("ACE_GOOGLE_REFRESH_TOKEN", ""),
    )
    uvicorn.run(create_app(config), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
