"""The one way the tests and the harness tools build a signed-in Campaign API client."""

import httpx

HTTP_TIMEOUT_SECONDS = 30


def api_client(base_url: str, token: str) -> httpx.Client:
    """A Campaign API client that sends `token` as its bearer token."""
    return httpx.Client(
        base_url=base_url,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {token}"},
    )
