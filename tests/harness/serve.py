"""Run the fast-depth stack until killed, for the browser seam (Playwright)."""

import os
import signal
import threading

from tests.harness.stack import Stack


def main() -> None:
    stack = Stack(
        api_port=int(os.environ["ACE_API_PORT"]),
        dex_port=int(os.environ["ACE_DEX_PORT"]),
        web_origin=f"http://127.0.0.1:{os.environ['ACE_WEB_PORT']}",
        # A spec that steers the simulated audience needs to know where the fake listens.
        marketo_port=int(os.environ["ACE_MARKETO_PORT"])
        if "ACE_MARKETO_PORT" in os.environ
        else None,
    ).start()
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    done.wait()
    stack.stop()


if __name__ == "__main__":
    main()
