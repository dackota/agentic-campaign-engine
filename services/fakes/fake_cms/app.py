"""A fake CMS shaped like a headless CMS's REST API (Strapi-style `data` envelopes).

- `PUT /api/pages/{slug}` creates or replaces the page with that slug. It is idempotent: a
  repeat keeps one page with the same `id`. `writes` counts the PUTs the page has had.
- `GET /api/pages/{slug}` and `GET /api/pages` read pages back, so a test can check from
  the outside what was published.
- `PUT /_fault` (test hook): the next PUT is kept, then answered with a 503.
"""

import threading
from typing import Any

from ace_engine import telemetry
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MAX_SLUG_CHARS = 100
MAX_BODY_CHARS = 500_000


class Fault(BaseModel):
    drop_next_reply: bool = False


class PageIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(max_length=MAX_BODY_CHARS)
    callToAction: str = Field(default="", max_length=255)  # noqa: N815 (the CMS's name)


class _Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pages: dict[str, dict[str, Any]] = {}
        self.fault = Fault()


def create_app() -> FastAPI:
    store = _Store()
    app = FastAPI()
    telemetry.instrument_app(app, "fake-cms")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/_fault", status_code=204)
    def set_fault(body: Fault) -> Response:
        with store.lock:
            store.fault = body
        return Response(status_code=204)

    @app.put("/api/pages/{slug}", response_model=None)
    def put_page(slug: str, body: PageIn) -> JSONResponse | dict[str, Any]:
        if len(slug) > MAX_SLUG_CHARS:
            raise HTTPException(status_code=422, detail="slug is too long")
        with store.lock:
            page = store.pages.get(slug) or {"id": len(store.pages) + 1, "slug": slug, "writes": 0}
            store.pages[slug] = {**page, **body.model_dump(), "writes": page["writes"] + 1}
            saved = dict(store.pages[slug])
            is_dropped = store.fault.drop_next_reply
            store.fault = Fault()
        if is_dropped:
            return JSONResponse({"error": {"status": 503}}, status_code=503)
        return {"data": saved}

    @app.get("/api/pages/{slug}")
    def get_page(slug: str) -> dict[str, Any]:
        with store.lock:
            page = store.pages.get(slug)
        if page is None:
            raise HTTPException(status_code=404, detail="page not found")
        return {"data": dict(page)}

    @app.get("/api/pages")
    def list_pages() -> dict[str, Any]:
        with store.lock:
            return {"data": [dict(p) for p in store.pages.values()]}

    return app
