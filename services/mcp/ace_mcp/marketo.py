"""The read-only MCP server for the Marketo-shaped fake: email programs and their sends."""

import os
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import FastAPI

from ace_mcp.args import segment
from ace_mcp.server import Reader, Tool, schema, serve
from ace_mcp.server import create_app as build_app
from ace_mcp.upstream import HTTP_TIMEOUT_SECONDS, HttpReader

NAME = "ace-mcp-marketo"
API = "/rest/asset/v1"


def _list_programs(reader: Reader, args: dict[str, Any]) -> object:
    return reader.get(f"{API}/programs.json", externalId=str(args.get("external_id", "")))


def _get_program(reader: Reader, args: dict[str, Any]) -> object:
    return reader.get(f"{API}/program/{segment(args, 'program_id')}.json")


TOOLS = (
    Tool(
        "list_programs",
        "List Marketo email programs, optionally by the campaign id they carry.",
        schema(external_id="The campaign id the program was made for"),
        _list_programs,
    ),
    Tool(
        "get_program",
        "Read one Marketo email program, with its sends, by its ID.",
        schema(["program_id"], program_id="The program's ID"),
        _get_program,
    ),
)


def create_app(client: httpx.Client, client_id: str, client_secret: str) -> FastAPI:
    reader = HttpReader(
        client,
        token_path="/identity/oauth/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    return build_app(NAME, TOOLS, reader)


def app_from_env(environ: Mapping[str, str] = os.environ) -> FastAPI:
    client = httpx.Client(base_url=environ["ACE_MARKETO_URL"], timeout=HTTP_TIMEOUT_SECONDS)
    return create_app(
        client, environ["ACE_MARKETO_CLIENT_ID"], environ["ACE_MARKETO_CLIENT_SECRET"]
    )


if __name__ == "__main__":
    serve(app_from_env())
