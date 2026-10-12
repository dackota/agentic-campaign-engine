"""The read-only MCP server for the asset library (an S3 bucket): list and read assets."""

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
from fastapi import FastAPI

from ace_mcp.server import Reader, Tool, schema, serve
from ace_mcp.server import create_app as build_app
from ace_mcp.upstream import HTTP_TIMEOUT_SECONDS, HttpReader

NAME = "ace-mcp-assets"
S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
TEXT_PREVIEW_BYTES = 8_000


def _list_assets(bucket: str) -> Any:
    def run(reader: Reader, args: dict[str, Any]) -> Any:
        listing = reader.get_response(
            f"/{bucket}", **{"list-type": "2", "prefix": str(args.get("prefix", ""))}
        )
        root = ElementTree.fromstring(listing.text)
        return {
            "assets": [
                {
                    "key": item.findtext(f"{S3_NAMESPACE}Key"),
                    "size": int(item.findtext(f"{S3_NAMESPACE}Size") or 0),
                }
                for item in root.iter(f"{S3_NAMESPACE}Contents")
            ]
        }

    return run


def _get_asset(bucket: str) -> Any:
    def run(reader: Reader, args: dict[str, Any]) -> Any:
        response = reader.get_response(f"/{bucket}/{quote(str(args['key']), safe='/')}")
        content_type = response.headers.get("content-type", "")
        reply: dict[str, Any] = {
            "key": args["key"],
            "content_type": content_type,
            "size": len(response.content),
        }
        if content_type.startswith(("text/", "application/json")):
            reply["text"] = response.content[:TEXT_PREVIEW_BYTES].decode(errors="replace")
        return reply

    return run


def tools_for(bucket: str) -> tuple[Tool, ...]:
    return (
        Tool(
            "list_assets",
            "List the asset library's files, optionally under a key prefix.",
            schema(prefix="Only keys that start with this"),
            _list_assets(bucket),
        ),
        Tool(
            "get_asset",
            "Read one asset's details by key; text assets include their text.",
            schema(["key"], key="The asset's key"),
            _get_asset(bucket),
        ),
    )


def create_app(client: httpx.Client, bucket: str) -> FastAPI:
    return build_app(NAME, tools_for(bucket), HttpReader(client))


def app_from_env(environ: Mapping[str, str] = os.environ) -> FastAPI:
    client = httpx.Client(base_url=environ["ACE_S3_URL"], timeout=HTTP_TIMEOUT_SECONDS)
    return create_app(client, environ["ACE_S3_BUCKET"])


if __name__ == "__main__":
    serve(app_from_env())
