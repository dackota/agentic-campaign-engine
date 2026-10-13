from collections.abc import Callable, Iterator

import httpx
import pytest

from tests.api.helpers import APPROVER, OWNER
from tests.harness.api_client import api_client
from tests.harness.stack import Stack

SignIn = Callable[[str], httpx.Client]


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    with Stack() as running:
        yield running


@pytest.fixture
def sign_in(stack: Stack) -> Iterator[SignIn]:
    """A Campaign API client that sends the named demo user's real Dex token."""
    clients: list[httpx.Client] = []

    def client_for(email: str) -> httpx.Client:
        client = api_client(stack.api_url, stack.dex.token(email))
        clients.append(client)
        return client

    yield client_for
    for client in clients:
        client.close()


@pytest.fixture
def api(stack: Stack, sign_in: SignIn) -> httpx.Client:
    """Signed in as a Demand Gen owner: creates and runs campaigns."""
    stack.agent.script([])
    return sign_in(OWNER)


@pytest.fixture
def approver(sign_in: SignIn) -> httpx.Client:
    """Signed in as a Demand Gen approver: approves the owner's campaigns."""
    return sign_in(APPROVER)
