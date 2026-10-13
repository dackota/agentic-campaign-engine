"""Seam 1: the step cache persists across gate runs. Two stacks that share a database volume:
the second run of unchanged steps makes no model call."""

import contextlib
import uuid
from collections.abc import Iterator

import httpx
import pytest
from testcontainers.core.docker_client import DockerClient

from evals.golden import GoldenReport
from evals.runner import run_golden
from tests.api.helpers import OWNER
from tests.harness.stack import Stack


@pytest.fixture
def volume() -> Iterator[str]:
    name = f"ace-evals-test-{uuid.uuid4().hex[:8]}"
    yield name
    with contextlib.suppress(Exception):
        DockerClient().client.volumes.get(name).remove(force=True)


def run_on_stack(volume: str, entry: GoldenReport) -> tuple[int, int, int]:
    with Stack(data_volume=volume) as stack:
        stack.agent.script([])
        with httpx.Client(
            base_url=stack.api_url,
            timeout=30,
            headers={"Authorization": f"Bearer {stack.dex.token(OWNER)}"},
        ) as api:
            [result] = run_golden(api, [entry])
        return result.cache_hits, result.agent_steps, len(stack.agent.message_ids())


def test_rerun_on_a_new_stack_with_the_same_volume_makes_zero_model_calls(volume: str) -> None:
    entry = GoldenReport(
        "persist", f"Volt Typhoon targets edge routers\ncase {uuid.uuid4().hex}", ("edge routers",)
    )

    first_hits, first_steps, first_calls = run_on_stack(volume, entry)
    hits, steps, calls = run_on_stack(volume, entry)

    assert (first_hits, first_calls > 0) == (0, True)
    assert steps == first_steps > 0
    assert hits == steps
    assert calls == 0
