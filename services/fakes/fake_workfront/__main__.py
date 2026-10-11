"""Run the fake Workfront: `python -m fake_workfront`. Config comes from `ACE_WORKFRONT_*`."""

import os

import uvicorn

from fake_workfront.app import config_from_env, create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def main() -> None:
    uvicorn.run(create_app(config_from_env(os.environ)), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
