"""The fake services (CMS, S3, Slack, Google) reached in-process: one transport that sends
each request to the fake app that owns its host, so the worker's code runs against the real
fakes with no socket."""

import httpx
from fastapi import FastAPI


class FakeServices(httpx.AsyncBaseTransport):
    """`FakeServices({"cms": cms_app, "s3": s3_app})` answers `http://cms/...` from the CMS
    app and `http://s3/...` from the S3 app. A host nobody owns is an error, not a 404."""

    def __init__(self, apps: dict[str, FastAPI]) -> None:
        self._transports = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}
        self.seen: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        transport = self._transports.get(request.url.host)
        if transport is None:
            raise httpx.ConnectError(f"no fake service at {request.url.host}", request=request)
        return await transport.handle_async_request(request)

    def client(self) -> httpx.AsyncClient:
        """A client that talks to the fakes, for a test that calls their test hooks."""
        return httpx.AsyncClient(transport=self)
