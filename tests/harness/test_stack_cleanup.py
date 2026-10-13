"""A stack that fails to start removes what it started. Testcontainers' atexit hook removes
its reaper (Ryuk) before the reaper can clean up, so nothing else would."""

import pytest
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.labels import LABEL_SESSION_ID, SESSION_ID

from tests.harness.dex import Dex
from tests.harness.stack import Pinned, Stack, free_port


def _session_containers() -> set[str]:
    client = DockerClient().client
    try:
        found = client.containers.list(
            all=True, filters={"label": f"{LABEL_SESSION_ID}={SESSION_ID}"}
        )
        return {c.id for c in found if c.id}
    finally:
        client.close()


def test_a_stack_whose_dex_port_is_taken_leaves_no_container_behind() -> None:
    # Another run's Dex holds the port, as when two browser runs share the default port.
    pinned = Pinned(dex_port=free_port())
    other_run = Dex(pinned.dex_port or 0, pinned.web_origin).start()
    try:
        before = _session_containers()
        stack = Stack(pinned=pinned)

        with pytest.raises(Exception, match="already allocated"):
            stack.start()

        assert _session_containers() == before
        stack.stop()  # a second stop is a no-op
    finally:
        other_run.stop()
