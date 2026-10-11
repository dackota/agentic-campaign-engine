"""Run the fake Slack: `python -m fake_slack`. The token comes from `ACE_SLACK_TOKEN`."""

import os

import uvicorn

from fake_slack.app import SlackConfig, create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def main() -> None:
    uvicorn.run(
        create_app(SlackConfig(token=os.environ.get("ACE_SLACK_TOKEN", ""))), host=HOST, port=PORT
    )


if __name__ == "__main__":
    main()
