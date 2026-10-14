"""A stack that fails to start removes what it started. Testcontainers' atexit hook removes
its reaper (Ryuk) before the reaper can clean up, so nothing else would."""

import os
import socket
import subprocess
import sys

import pytest
from docker.errors import APIError, NotFound
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.labels import LABEL_SESSION_ID, SESSION_ID

from tests.harness.dex import Dex
from tests.harness.stack import (
    HOST_LABEL,
    PID_LABEL,
    POSTGRES_IMAGE,
    RUN_LABEL,
    Pinned,
    Stack,
    free_port,
)


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


def _orphan(labels: dict[str, str]) -> str:
    client = DockerClient().client
    try:
        return str(
            client.containers.run(POSTGRES_IMAGE, "sleep 300", detach=True, labels=labels).id
        )
    finally:
        client.close()


def _exists(container_id: str) -> bool:
    client = DockerClient().client
    try:
        return bool(client.containers.list(all=True, filters={"id": container_id}))
    finally:
        client.close()


def _remove(container_id: str) -> None:
    client = DockerClient().client
    try:
        for c in client.containers.list(all=True, filters={"id": container_id}):
            c.remove(force=True, v=True)
    finally:
        client.close()


def _labels(pid: int, host: str | None = None) -> dict[str, str]:
    return {RUN_LABEL: "orphan-test", PID_LABEL: str(pid), HOST_LABEL: host or socket.gethostname()}


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _start_new_stack_beside(container_id: str) -> bool:
    try:
        with Stack():
            pass
        return _exists(container_id)
    finally:
        _remove(container_id)


def test_a_new_stack_removes_a_container_of_a_dead_process() -> None:
    assert _start_new_stack_beside(_orphan(_labels(_dead_pid()))) is False


def test_a_new_stack_keeps_a_container_of_a_live_process() -> None:
    assert _start_new_stack_beside(_orphan(_labels(os.getppid()))) is True


def test_a_new_stack_keeps_a_container_of_another_host() -> None:
    assert _start_new_stack_beside(_orphan(_labels(_dead_pid(), "another-host"))) is True


def test_a_new_stack_keeps_a_container_without_the_run_label() -> None:
    labels = {PID_LABEL: str(_dead_pid()), HOST_LABEL: socket.gethostname()}
    assert _start_new_stack_beside(_orphan(labels)) is True


class _FakeApi:
    """Docker's low-level API: listing returns dicts (no per-container inspect) and
    removing a container another worker already removed raises NotFound."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.removed: list[str] = []

    def containers(self, **_: object) -> list[dict[str, object]]:
        labels = {RUN_LABEL: "x", PID_LABEL: str(_dead_pid()), HOST_LABEL: socket.gethostname()}
        return [{"Id": "gone", "Labels": labels}, {"Id": "next", "Labels": labels}]

    def remove_container(self, container_id: str, **_: object) -> None:
        if container_id == "gone":
            raise self.error
        self.removed.append(container_id)


class _FakeClient:
    def __init__(self, error: Exception) -> None:
        self.api = _FakeApi(error)
        # docker-py's containers.list() inspects every container it lists, so a container
        # removed meanwhile raises from the list itself.
        self.containers = type("C", (), {"list": staticmethod(self._list)})()
        self._error = error

    def _list(self, **_: object) -> list[object]:
        raise self._error

    def close(self) -> None:
        pass


def _sweep_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> _FakeClient:
    fake = _FakeClient(error)
    monkeypatch.setattr(
        "tests.harness.stack.DockerClient", lambda: type("D", (), {"client": fake})()
    )
    Stack._remove_orphans()
    return fake


def test_orphan_cleanup_survives_a_container_removed_by_another_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _sweep_with(monkeypatch, NotFound("gone"))
    assert fake.api.removed == ["next"]


def test_orphan_cleanup_raises_other_docker_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(APIError):
        _sweep_with(monkeypatch, APIError("boom"))
