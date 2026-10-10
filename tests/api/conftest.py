from collections.abc import Iterator

import httpx
import pytest

from tests.harness.stack import Stack


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    with Stack() as running:
        yield running


@pytest.fixture
def api(stack: Stack) -> Iterator[httpx.Client]:
    stack.agent.script([])
    with httpx.Client(base_url=stack.api_url, timeout=30) as client:
        yield client
