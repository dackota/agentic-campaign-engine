"""Run the fast-depth stack until killed, for the browser seam (Playwright)."""

import os
import signal
import threading

from tests.harness.stack import Stack


def main() -> None:
    stack = Stack(api_port=int(os.environ["ACE_API_PORT"])).start()
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    done.wait()
    stack.stop()


if __name__ == "__main__":
    main()
