"""The four read-only MCP servers over HTTP, each reading the real fake it fronts."""

import json
from typing import Any

import httpx
from ace_mcp import assets, cms, marketo, workfront
from ace_mcp.registry import SERVERS
from fake_cms.app import create_app as create_cms
from fake_marketo.app import MarketoConfig
from fake_marketo.app import create_app as create_marketo
from fake_s3.app import create_app as create_s3
from fake_workfront.app import WorkfrontConfig
from fake_workfront.app import create_app as create_workfront
from fastapi.testclient import TestClient

CLIENT_ID = "mcp-client"
CLIENT_SECRET = "mcp-client-secret-value"
HOOK = "http://127.0.0.1:9/hook"
WRITE_VERBS = ("create", "update", "delete", "put", "post", "send", "publish", "set", "upsert")


def rpc(mcp: TestClient, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = mcp.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def call(mcp: TestClient, tool: str, arguments: dict[str, Any]) -> Any:
    result = rpc(mcp, "tools/call", {"name": tool, "arguments": arguments})["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def listed(mcp: TestClient) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = rpc(mcp, "tools/list")["result"]["tools"]
    return tools


def workfront_stack() -> tuple[TestClient, TestClient]:
    fake = TestClient(
        create_workfront(WorkfrontConfig(CLIENT_ID, CLIENT_SECRET, HOOK, "hook-secret"))
    )
    token = fake.post(
        "/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    ).json()["access_token"]
    seed = {"Authorization": f"Bearer {token}"}
    project = fake.post(
        "/attask/api/v15.0/proj", json={"name": "Volt", "externalID": "c-1"}, headers=seed
    ).json()["data"]
    fake.post(
        "/attask/api/v15.0/task",
        json={"name": "Review", "projectID": project["ID"], "externalID": "c-1"},
        headers=seed,
    )
    return fake, TestClient(workfront.create_app(fake, CLIENT_ID, CLIENT_SECRET))


def test_workfront_server_reads_project_details_and_tasks() -> None:
    fake, mcp = workfront_stack()
    found = call(mcp, "search_projects", {"external_id": "c-1"})["data"]
    assert [p["name"] for p in found] == ["Volt"]

    project = call(mcp, "get_project", {"project_id": found[0]["ID"]})["data"]
    tasks = call(mcp, "search_tasks", {"project_id": found[0]["ID"]})["data"]

    assert project["externalID"] == "c-1"
    assert [t["name"] for t in tasks] == ["Review"]
    assert call(mcp, "get_task", {"task_id": tasks[0]["ID"]})["data"]["status"] == "NEW"


def test_marketo_server_reads_programs() -> None:
    fake = TestClient(create_marketo(MarketoConfig(CLIENT_ID, CLIENT_SECRET, HOOK, "hook-secret")))
    token = fake.post(
        "/identity/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    ).json()["access_token"]
    fake.post(
        "/rest/asset/v1/programs.json",
        json={"name": "Volt", "externalId": "c-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    mcp = TestClient(marketo.create_app(fake, CLIENT_ID, CLIENT_SECRET))

    programs = call(mcp, "list_programs", {"external_id": "c-1"})["result"]

    assert [p["name"] for p in programs] == ["Volt"]
    assert call(mcp, "get_program", {"program_id": programs[0]["id"]})["result"][0]["id"] == 1


def test_cms_server_reads_pages() -> None:
    fake = TestClient(create_cms())
    fake.put("/api/pages/volt", json={"title": "Volt", "body": "hello"})
    mcp = TestClient(cms.create_app(fake))

    assert [p["slug"] for p in call(mcp, "list_pages", {})["data"]] == ["volt"]
    assert call(mcp, "get_page", {"slug": "volt"})["data"]["title"] == "Volt"


def test_asset_server_reads_objects() -> None:
    fake = TestClient(create_s3())
    fake.put("/bucket")
    fake.put("/bucket/img/a.txt", content=b"asset-bytes", headers={"content-type": "text/plain"})
    mcp = TestClient(assets.create_app(fake, "bucket"))

    listing = call(mcp, "list_assets", {"prefix": "img/"})
    assert [a["key"] for a in listing["assets"]] == ["img/a.txt"]
    assert call(mcp, "get_asset", {"key": "img/a.txt"})["text"] == "asset-bytes"


def test_every_server_lists_only_read_only_tools_and_never_writes_upstream() -> None:
    seen: list[tuple[str, str]] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"access_token": "t", "data": [], "result": []})

    client = httpx.Client(transport=httpx.MockTransport(record), base_url="http://up")
    apps = {
        "ace-mcp-workfront": workfront.create_app(client, CLIENT_ID, CLIENT_SECRET),
        "ace-mcp-marketo": marketo.create_app(client, CLIENT_ID, CLIENT_SECRET),
        "ace-mcp-cms": cms.create_app(client),
        "ace-mcp-assets": assets.create_app(client, "bucket"),
    }

    assert set(apps) == set(SERVERS)
    for name, app in apps.items():
        mcp = TestClient(app)
        tools = listed(mcp)
        assert tools, name
        for tool in tools:
            assert tool["annotations"]["readOnlyHint"] is True, (name, tool["name"])
            assert not tool["name"].startswith(WRITE_VERBS), (name, tool["name"])
            required = tool["inputSchema"].get("required", [])
            call_args = {k: "x" for k in required}
            rpc(mcp, "tools/call", {"name": tool["name"], "arguments": call_args})
    assert seen, "the tools reached their upstream"
    # Only reads, and the OAuth token exchange: never a write.
    for method, path in seen:
        assert method == "GET" or path.endswith("/token"), (method, path)


def test_initialize_and_unknown_tool_follow_the_protocol() -> None:
    mcp = TestClient(cms.create_app(TestClient(create_cms())))

    init = rpc(
        mcp,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )["result"]
    assert "tools" in init["capabilities"]
    unknown = rpc(mcp, "tools/call", {"name": "delete_page", "arguments": {}})
    assert unknown["error"]["code"] == -32602
    assert (
        mcp.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code
        == 202
    )
