"""The read-only MCP server the research and writer agents search past learnings with.

One runs per team: it reads the database as that team (`row_security.for_team`), so a
team's agents only ever find their own team's learnings. Its one tool is a read.
"""

import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from ace_engine import db, learnings, row_security
from ace_engine.env import database_url_from_env
from ace_engine.settings import Depth
from fastapi import FastAPI
from sqlalchemy.engine import Engine

from ace_mcp.server import Reader, Tool, schema, serve
from ace_mcp.server import create_app as build_app

NAME = "ace-mcp-learnings"
SEARCH_TOOL = "search_learnings"
Search = Callable[[str], list[learnings.Found]]


def _shown(found: learnings.Found) -> dict[str, Any]:
    learning = found.learning
    return {
        "id": str(learning.id),
        "text": learning.text,
        "reason": learning.reason,
        "metrics": learning.metrics,
        "campaign_id": str(learning.campaign_id),
        "campaign_title": found.campaign_title,
    }


def tools_for(search: Search) -> tuple[Tool, ...]:
    def run(_reader: Reader, args: Mapping[str, object]) -> object:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("query must not be blank")
        return [_shown(f) for f in search(query)]

    return (
        Tool(
            SEARCH_TOOL,
            "Search your team's past learnings: lines from earlier campaigns that won their "
            "A/B test, with why they won. Pass what you are about to write as the query.",
            schema(["query"], query="What you are about to write about"),
            run,
        ),
    )


def _no_search(_query: str) -> list[learnings.Found]:
    raise RuntimeError("this server was built only to list its tools")


# What `tools/list` shows; the no-write-tool check reads it from the registry.
TOOLS = tools_for(_no_search)


def create_app(engine: Engine, team: str, embed: learnings.Embed) -> FastAPI:
    """The server for `team`. A blank team sees no learnings, as row-level security says."""
    team_engine = row_security.for_team(engine, team)
    return build_app(NAME, tools_for(lambda q: learnings.search(team_engine, q, embed)), Reader())


def app_from_env(client: httpx.Client, environ: Mapping[str, str] = os.environ) -> FastAPI:
    """The server the environment describes; embeddings go over `client`, which the caller
    owns and closes."""
    embed = learnings.embedder_for(
        Depth.parse(environ.get("ACE_DEPTH", Depth.FAST)),
        environ.get("ACE_EMBEDDING_URL", ""),
        environ.get("ACE_EMBEDDING_MODEL", ""),
        client,
    )
    engine = db.make_engine(database_url_from_env(environ))
    return create_app(engine, environ.get("ACE_TEAM", ""), embed)


if __name__ == "__main__":
    with httpx.Client(timeout=learnings.EMBED_TIMEOUT_SECONDS) as embed_client:
        serve(app_from_env(embed_client))
