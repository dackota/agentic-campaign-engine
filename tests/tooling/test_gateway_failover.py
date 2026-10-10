"""S1 failover and team token limits, checked offline: manifests, scripts, mock, notes.

The live proof (fake OpenCode key fails over to the Anthropic-style mock, team A gets a
429 while team B gets a 200, tokens per team in the log) is
scripts/spike/gateway-failover-check.sh, run by tests/spike/test_gateway_failover_live.py.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "manifests/spike/gateway.yaml"
ANTHROPIC = ROOT / "manifests/spike/gateway-anthropic.yaml"
FAILOVER_TEST = ROOT / "manifests/spike/gateway-failover-test.yaml"
MOCK = ROOT / "manifests/spike/mock-llm.yaml"
INSTALL = ROOT / "scripts/spike/gateway-install.sh"
CHECK = ROOT / "scripts/spike/gateway-failover-check.sh"
LOG = ROOT / "docs/spike-log.md"
ADR = ROOT / "docs/decisions/llm-gateway-failover.md"
TEAMS = ("team-a", "team-b")
MOCK_START_TIMEOUT_S = 10


def _docs(path: Path) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _named(path: Path, kind: str, name: str) -> dict[str, Any]:
    return next(d for d in _docs(path) if d["kind"] == kind and d["metadata"]["name"] == name)


def _groups(backend: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [g["providers"] for g in backend["spec"]["ai"]["groups"]]


def _policies_for(path: Path, kind: str, name: str) -> list[dict[str, Any]]:
    return [
        d
        for d in _docs(path)
        if d["kind"] == "AgentgatewayPolicy"
        and any(t["kind"] == kind and t["name"] == name for t in d["spec"]["targetRefs"])
    ]


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_main_backend_has_opencode_then_anthropic_style_group() -> None:
    backend = _named(GATEWAY, "AgentgatewayBackend", "opencode-go")
    first, second = _groups(backend)
    assert first[0]["host"] == "opencode.ai"
    assert "openai" in first[0]
    assert first[0]["policies"]["auth"]["secretRef"]["name"] == "opencode-go-key"
    # Until the user adds an Anthropic key, priority 2 is the mock's Anthropic route.
    assert "anthropic" in second[0]
    assert second[0]["host"].startswith("mock-llm.kagent")
    assert second[0]["path"] == "/v1/messages"


def test_main_backend_fails_over_on_key_errors_and_outages() -> None:
    health = [
        p["spec"]["backend"]["health"]
        for p in _policies_for(GATEWAY, "AgentgatewayBackend", "opencode-go")
        if "backend" in p["spec"]
    ]
    assert health, "no health policy on the opencode-go backend"
    cond = health[0]["unhealthyCondition"]
    for code in ("401", "403", "500"):
        assert code in cond, code
    # The gateway's own token-limit 429 counts against the backend, so a 429 rule would
    # let one team over budget evict OpenCode Go for every team (seen live).
    assert "429" not in cond
    assert health[0]["eviction"]["consecutiveFailures"] == 1


def test_routes_retry_so_the_same_call_succeeds() -> None:
    for route in ("opencode-go", *TEAMS):
        retries = [
            p["spec"]["traffic"]["retry"]
            for p in _policies_for(GATEWAY, "HTTPRoute", route)
            if "retry" in p["spec"].get("traffic", {})
        ]
        assert retries, route
        assert {401, 403, 500} <= set(retries[0]["codes"])
        assert 429 not in retries[0]["codes"]


def test_real_anthropic_backend_reads_key_from_secret() -> None:
    backend = _named(ANTHROPIC, "AgentgatewayBackend", "opencode-go")
    first, second = _groups(backend)
    assert first[0]["host"] == "opencode.ai"
    assert "anthropic" in second[0]
    assert "host" not in second[0], "real Anthropic uses the provider's default host"
    assert second[0]["policies"]["auth"]["secretRef"]["name"] == "anthropic-key"
    assert not any(d["kind"] == "Secret" for d in _docs(ANTHROPIC))


def test_install_reads_anthropic_key_on_stdin_only_when_present() -> None:
    code = _code(INSTALL)
    assert "ANTHROPIC_API_KEY" in code
    assert re.search(
        r'printf %s "\$ANTHROPIC_KEY" \|[^\n]*\\\n\s*--from-file=Authorization=/dev/stdin', code
    )
    uses = [line.strip() for line in code.splitlines() if '"$ANTHROPIC_KEY"' in line]
    assert all(
        u.startswith(('if [ -n "$ANTHROPIC_KEY" ]', 'printf %s "$ANTHROPIC_KEY" |')) for u in uses
    ), uses
    assert "gateway-anthropic.yaml" in code


def test_env_example_lists_anthropic_key_without_value() -> None:
    assert re.search(r"^ANTHROPIC_API_KEY=$", (ROOT / ".env.example").read_text(), re.M)


def test_failover_test_backend_uses_fake_key_not_the_real_secret() -> None:
    backend = _named(FAILOVER_TEST, "AgentgatewayBackend", "failover-test")
    first, second = _groups(backend)
    assert first[0]["host"] == "opencode.ai"
    auth = first[0]["policies"]["auth"]
    assert "secretRef" not in auth
    assert "not-a-real-key" in auth["key"]
    assert "anthropic" in second[0] and second[0]["path"] == "/v1/messages"
    assert not any(d["kind"] == "Secret" for d in _docs(FAILOVER_TEST))
    route = _named(FAILOVER_TEST, "HTTPRoute", "failover-test")
    assert route["spec"]["rules"][0]["backendRefs"][0]["name"] == "failover-test"


def test_each_team_has_own_model_config_and_route() -> None:
    for team in TEAMS:
        mc = _named(GATEWAY, "ModelConfig", f"{team}-model")
        assert mc["spec"]["openAI"]["baseUrl"].endswith(f"/{team}/v1")
        route = _named(GATEWAY, "HTTPRoute", team)
        rule = route["spec"]["rules"][0]
        assert rule["matches"][0]["path"]["value"] == f"/{team}/v1"
        assert rule["backendRefs"][0]["name"] == "opencode-go"
        sets = {h["name"]: h["value"] for h in rule["filters"][0]["requestHeaderModifier"]["set"]}
        assert sets["x-team"] == team


def test_each_team_route_has_its_own_token_limit() -> None:
    for team in TEAMS:
        limits = [
            p["spec"]["traffic"]["rateLimit"]["local"]
            for p in _policies_for(GATEWAY, "HTTPRoute", team)
            if "rateLimit" in p["spec"].get("traffic", {})
        ]
        assert len(limits) == 1, team
        assert limits[0][0]["tokens"] > 0
        assert limits[0][0]["unit"] == "Minutes"


def test_access_log_names_the_team() -> None:
    policy = _named(GATEWAY, "AgentgatewayPolicy", "log-opencode-headers")
    attrs = {
        a["name"]: a["expression"]
        for a in policy["spec"]["frontend"]["accessLog"]["attributes"]["add"]
    }
    assert "x-team" in attrs["team"]


def test_check_script_covers_failover_429_and_tokens_per_team() -> None:
    code = _code(CHECK)
    for needle in (
        "--context",
        "failover-test",
        "team-a",
        "team-b",
        "429",
        "input_tokens",
        "team=",
    ):
        assert needle in code, needle
    assert "gateway-failover-test.yaml" in code


def test_no_key_in_git() -> None:
    for path in (GATEWAY, ANTHROPIC, FAILOVER_TEST, INSTALL, CHECK):
        assert not re.search(r"sk-[A-Za-z0-9]{16,}", path.read_text()), path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def mock_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    cm = _named(MOCK, "ConfigMap", "mock-llm")
    server = tmp_path_factory.mktemp("mock") / "server.py"
    server.write_text(cm["data"]["server.py"])
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-I", str(server)],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + MOCK_START_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url + "/v1/models", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    try:
        yield url
    finally:
        proc.terminate()
        proc.wait()


def _post(url: str, body: dict[str, Any]) -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return bytes(resp.read())


def test_mock_answers_anthropic_messages(mock_url: str) -> None:
    body = {
        "model": "mock-anthropic",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "What is 7 times 6?"}]}],
    }
    out = json.loads(_post(mock_url + "/v1/messages", body))
    assert out["type"] == "message"
    assert out["role"] == "assistant"
    assert out["content"] == [{"type": "text", "text": "42"}]
    assert out["usage"]["input_tokens"] > 0 and out["usage"]["output_tokens"] > 0


def test_mock_streams_anthropic_messages(mock_url: str) -> None:
    body = {
        "model": "mock-anthropic",
        "max_tokens": 64,
        "stream": True,
        "messages": [{"role": "user", "content": "What is 7 times 6?"}],
    }
    raw = _post(mock_url + "/v1/messages", body).decode()
    events = re.findall(r"^event: (\S+)$", raw, re.M)
    assert events[0] == "message_start" and events[-1] == "message_stop"
    assert "content_block_delta" in events and "message_delta" in events
    assert '"text": "42"' in raw or '"text":"42"' in raw


def test_mock_usage_grows_with_the_prompt(mock_url: str) -> None:
    def usage(text: str) -> int:
        body = {"model": "mock", "messages": [{"role": "user", "content": text}]}
        return int(
            json.loads(_post(mock_url + "/v1/chat/completions", body))["usage"]["prompt_tokens"]
        )

    assert usage("x" * 40_000) > usage("hi") >= 1


def test_spike_log_answers_cross_style_failover() -> None:
    text = LOG.read_text()
    heading = "\n## 18. S1: failover and team token limits"
    assert heading in text
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    assert re.search(r"OpenAI-style", section) and re.search(r"Anthropic-style", section)
    assert re.search(r"failover (works|does not work) across", section)
    assert "owed" in section.lower(), "the real Anthropic run is owed after the merge"
    assert re.search(r"20\d\d-\d\d-\d\d", section)


def test_adr_covers_gateway_order_and_claude_login() -> None:
    text = ADR.read_text()
    for needle in ("agentgateway", "OpenCode Go", "Anthropic", "Claude login", "priority"):
        assert needle in text, needle
    assert re.search(r"Status: accepted", text)
