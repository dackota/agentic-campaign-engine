"""The read-only MCP server for the CMS fake: landing pages."""

import os
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import FastAPI

from ace_mcp.args import segment
from ace_mcp.server import Reader, Tool, schema, serve
from ace_mcp.server import create_app as build_app
from ace_mcp.upstream import HTTP_TIMEOUT_SECONDS, HttpReader

NAME = "ace-mcp-cms"


def _list_pages(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get("/api/pages")


def _get_page(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(f"/api/pages/{segment(args, 'slug')}")


TOOLS = (
    Tool("list_pages", "List the CMS's landing pages.", schema(), _list_pages),
    Tool(
        "get_page",
        "Read one CMS landing page by its slug.",
        schema(["slug"], slug="The page's slug"),
        _get_page,
    ),
)


def create_app(client: httpx.Client) -> FastAPI:
    return build_app(NAME, TOOLS, HttpReader(client))


def app_from_env(environ: Mapping[str, str] = os.environ) -> FastAPI:
    return create_app(httpx.Client(base_url=environ["ACE_CMS_URL"], timeout=HTTP_TIMEOUT_SECONDS))


if __name__ == "__main__":
    serve(app_from_env())
