"""The read-only MCP server for the Workfront-shaped fake: projects, tasks, approvals."""

import os
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import FastAPI

from ace_mcp.server import Reader, Tool, schema, serve
from ace_mcp.server import create_app as build_app
from ace_mcp.upstream import HttpReader

NAME = "ace-mcp-workfront"
API = "/attask/api/v15.0"


def _get_project(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(f"{API}/proj/{args['project_id']}")


def _search_projects(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(f"{API}/proj/search", externalID=str(args.get("external_id", "")))


def _get_task(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(f"{API}/task/{args['task_id']}")


def _search_tasks(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(
        f"{API}/task/search",
        projectID=str(args.get("project_id", "")),
        externalID=str(args.get("external_id", "")),
    )


def _search_approvals(reader: Reader, args: dict[str, Any]) -> Any:
    return reader.get(f"{API}/appr/search", taskID=str(args.get("task_id", "")))


TOOLS = (
    Tool(
        "get_project",
        "Read one Workfront project's details by its ID.",
        schema(["project_id"], project_id="The project's ID"),
        _get_project,
    ),
    Tool(
        "search_projects",
        "Find Workfront projects, optionally by the campaign id (externalID) they carry.",
        schema(external_id="The campaign id the project was made for"),
        _search_projects,
    ),
    Tool(
        "get_task",
        "Read one Workfront task, with its status, by its ID.",
        schema(["task_id"], task_id="The task's ID"),
        _get_task,
    ),
    Tool(
        "search_tasks",
        "Find Workfront tasks of a project or of a campaign id.",
        schema(project_id="The project's ID", external_id="The campaign id"),
        _search_tasks,
    ),
    Tool(
        "search_approvals",
        "Find the approvals on a Workfront task.",
        schema(task_id="The task's ID"),
        _search_approvals,
    ),
)


def create_app(client: httpx.Client, client_id: str, client_secret: str) -> FastAPI:
    reader = HttpReader(
        client, token_path="/oauth2/token", client_id=client_id, client_secret=client_secret
    )
    return build_app(NAME, TOOLS, reader)


def app_from_env(environ: Mapping[str, str] = os.environ) -> FastAPI:
    client = httpx.Client(base_url=environ["ACE_WORKFRONT_URL"], timeout=10)
    return create_app(
        client, environ["ACE_WORKFRONT_CLIENT_ID"], environ["ACE_WORKFRONT_CLIENT_SECRET"]
    )


if __name__ == "__main__":
    serve(app_from_env())
