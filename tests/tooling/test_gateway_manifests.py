"""S1 gateway wiring, checked offline: manifests, check script, spike-log note.

The live proof (answer through the gateway, tokens per call, pod key check)
is scripts/spike/gateway-check.sh and needs the cluster, so make test skips it.
"""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "manifests/spike/gateway.yaml"
AGENT = ROOT / "manifests/spike/agent.yaml"
CHECK = ROOT / "scripts/spike/gateway-check.sh"
LOG = ROOT / "docs/spike-log.md"


def _docs(path: Path) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _kind(path: Path, kind: str) -> dict[str, Any]:
    return next(d for d in _docs(path) if d["kind"] == kind)


def test_model_config_points_at_gateway_with_v1() -> None:
    mc = _kind(GATEWAY, "ModelConfig")
    base = mc["spec"]["openAI"]["baseUrl"]
    assert base.startswith("http://") and "agentgateway" in base
    assert base.endswith("/v1")
    template = _kind(AGENT, "AgentTemplate")
    assert template["spec"]["modelConfig"]["name"] == mc["metadata"]["name"]


def test_route_sets_user_agent_and_session_header() -> None:
    route = _kind(GATEWAY, "HTTPRoute")
    filters = [f for r in route["spec"]["rules"] for f in r.get("filters", [])]
    sets = {
        h["name"].lower(): h["value"]
        for f in filters
        if f["type"] == "RequestHeaderModifier"
        for h in f["requestHeaderModifier"]["set"]
    }
    assert "x-opencode-session" in sets
    assert sets["user-agent"].startswith("agentic-campaign-engine/")


def test_backend_holds_key_by_secret_reference_only() -> None:
    backend = _kind(GATEWAY, "AgentgatewayBackend")
    assert backend["spec"]["policies"]["auth"]["secretRef"]["name"]
    assert backend["spec"]["ai"]["provider"]["host"] == "opencode.ai"
    assert not any(d["kind"] == "Secret" for d in _docs(GATEWAY))


def test_no_key_in_git() -> None:
    for path in (GATEWAY, AGENT, CHECK):
        assert not re.search(r"sk-[A-Za-z0-9]{16,}", path.read_text()), path
    example = ROOT / ".env.example"
    assert re.search(r"^OPENCODE_KEY=$", example.read_text(), re.M)


def test_check_script_covers_tokens_headers_and_pod_keys() -> None:
    text = CHECK.read_text()
    for needle in ("x-opencode-session", "user-agent", "tokens", "secretKeyRef", "OPENCODE_KEY"):
        assert needle in text, needle


def test_spike_log_records_session_header_note() -> None:
    text = LOG.read_text()
    assert "x-opencode-session" in text
    assert re.search(r"per (agent|conversation)", text)
