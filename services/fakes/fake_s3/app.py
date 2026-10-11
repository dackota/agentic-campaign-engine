"""A fake S3 store, path-style, for the objects a campaign publishes. It checks no
signature: it is a stand-in inside the cluster, not a security boundary.

- `PUT /{bucket}` makes a bucket (a repeat is fine).
- `PUT /{bucket}/{key}` stores an object, replacing the one at that key, and answers its
  `ETag`; the same bytes always give the same ETag. A missing bucket is a 404.
- `GET /{bucket}/{key}` reads an object. `GET /{bucket}?list-type=2[&prefix=]` is
  ListObjectsV2, as XML.
- `PUT /_fault` (test hook): the next object PUT is kept, then answered with a 503.
"""

import hashlib
import threading
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

MAX_OBJECT_BYTES = 5 * 1024 * 1024
S3_XMLNS = "http://s3.amazonaws.com/doc/2006-03-01/"
NO_SUCH_BUCKET = "NoSuchBucket"


class Fault(BaseModel):
    drop_next_reply: bool = False


class _Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.buckets: dict[str, dict[str, tuple[bytes, str]]] = {}
        self.fault = Fault()


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data, usedforsecurity=False).hexdigest()}"'


def create_app() -> FastAPI:
    store = _Store()
    app = FastAPI()

    def bucket(name: str) -> dict[str, tuple[bytes, str]]:
        found = store.buckets.get(name)
        if found is None:
            raise HTTPException(status_code=404, detail=NO_SUCH_BUCKET)
        return found

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/_fault", status_code=204)
    def set_fault(body: Fault) -> Response:
        with store.lock:
            store.fault = body
        return Response(status_code=204)

    @app.put("/{bucket_name}")
    def make_bucket(bucket_name: str) -> Response:
        with store.lock:
            store.buckets.setdefault(bucket_name, {})
        return Response(status_code=200)

    @app.put("/{bucket_name}/{key:path}")
    async def put_object(bucket_name: str, key: str, request: Request) -> Response:
        data = await request.body()
        if len(data) > MAX_OBJECT_BYTES:
            raise HTTPException(status_code=413, detail="object is too large")
        content_type = request.headers.get("content-type", "application/octet-stream")
        with store.lock:
            objects = bucket(bucket_name)
            objects[key] = (data, content_type)
            is_dropped = store.fault.drop_next_reply
            store.fault = Fault()
        if is_dropped:
            return Response(status_code=503)
        return Response(status_code=200, headers={"ETag": _etag(data)})

    @app.get("/{bucket_name}/{key:path}")
    def get_object(bucket_name: str, key: str) -> Response:
        with store.lock:
            found = bucket(bucket_name).get(key)
        if found is None:
            raise HTTPException(status_code=404, detail="NoSuchKey")
        data, content_type = found
        return Response(content=data, media_type=content_type, headers={"ETag": _etag(data)})

    @app.get("/{bucket_name}")
    def list_objects(bucket_name: str, prefix: str = "") -> Response:
        with store.lock:
            objects = dict(bucket(bucket_name))
        contents = "".join(
            f"<Contents><Key>{escape(key)}</Key><ETag>{escape(_etag(data))}</ETag>"
            f"<Size>{len(data)}</Size></Contents>"
            for key, (data, _) in sorted(objects.items())
            if key.startswith(prefix)
        )
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{S3_XMLNS}">'
            f"<Name>{escape(bucket_name)}</Name><Prefix>{escape(prefix)}</Prefix>"
            f"<IsTruncated>false</IsTruncated>{contents}</ListBucketResult>"
        )
        return Response(content=xml, media_type="application/xml")

    return app
