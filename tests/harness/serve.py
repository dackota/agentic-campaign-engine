"""Run the fast-depth stack until killed, for the browser seam (Playwright)."""

import contextlib
import os
import signal
import threading

from tests.harness.api_client import api_client
from tests.harness.demo_seed import seed
from tests.harness.stack import Pinned, Stack

# The browser specs run in parallel on one team, and one default-workflow campaign runs five
# model steps at once, so the engine's default team limit would make steps queue and the
# specs time out. The limit itself is tested at the API seam (tests/api/test_team_step_limit.py).
BROWSER_TEAM_STEP_LIMIT = 1000


def main() -> None:
    pinned = Pinned(
        api_port=int(os.environ["ACE_API_PORT"]),
        dex_port=int(os.environ["ACE_DEX_PORT"]),
        web_origin=f"http://127.0.0.1:{os.environ['ACE_WEB_PORT']}",
        # A spec that steers the simulated audience needs to know where the fake listens.
        marketo_port=int(os.environ["ACE_MARKETO_PORT"])
        if "ACE_MARKETO_PORT" in os.environ
        else None,
        # The browser spec for the alert banner posts to the alert webhook with this token.
        alert_webhook_token=os.environ.get("ACE_ALERT_WEBHOOK_TOKEN"),
    )
    # SIGTERM (Playwright's graceful shutdown) raises KeyboardInterrupt as SIGINT does, so the
    # stack stops even when the signal comes while it is still starting.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    with (
        contextlib.suppress(KeyboardInterrupt),
        Stack(pinned=pinned, team_step_limit=BROWSER_TEAM_STEP_LIMIT) as stack,
    ):
        # The demo recording starts from Acme's past campaigns, as `make seed-demo` leaves them.
        if os.environ.get("ACE_SEED_DEMO"):
            seed(lambda email: api_client(stack.api_url, stack.dex.token(email)))
        threading.Event().wait()


if __name__ == "__main__":
    main()
