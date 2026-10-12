"""How a server reaches the fake it fronts: GET only, with an OAuth2 client-credentials
token when the fake asks for one."""

from typing import Any

import httpx

from ace_mcp.server import Reader

HTTP_UNAUTHORIZED = 401
HTTP_TIMEOUT_SECONDS = 10


class HttpReader(Reader):
    def __init__(
        self,
        client: httpx.Client,
        *,
        token_path: str | None = None,
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self._client = client
        self._token_path = token_path
        self._credentials = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        # Tool calls run in worker threads; two may fetch a token at once, which only costs a
        # second fetch, so the cache needs no lock.
        self._token: str | None = None

    def _fetch_token(self) -> str:
        if self._token_path is None:
            raise RuntimeError("this upstream takes no token")
        response = self._client.post(self._token_path, data=self._credentials)
        response.raise_for_status()
        token = str(response.json()["access_token"])
        self._token = token
        return token

    def _headers(self) -> dict[str, str]:
        if self._token_path is None:
            return {}
        return {"Authorization": f"Bearer {self._token or self._fetch_token()}"}

    def get_response(self, path: str, **params: str) -> httpx.Response:
        wanted = {k: v for k, v in params.items() if v != ""}
        response = self._client.get(path, params=wanted, headers=self._headers())
        if response.status_code == HTTP_UNAUTHORIZED and self._token_path is not None:
            self._token = None  # expired: one fresh token, one retry
            response = self._client.get(path, params=wanted, headers=self._headers())
        response.raise_for_status()
        return response

    def get(self, path: str, **params: str) -> Any:
        return self.get_response(path, **params).json()
