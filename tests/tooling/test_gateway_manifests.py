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
INSTALL = ROOT / "scripts/spike/gateway-install.sh"
PINNED = ROOT / "docs/pinned-versions.md"
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


def _code(path: Path) -> str:
    """The script without its comment lines."""
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _section(text: str, number: int) -> str:
    return text.split(f"\n## {number}.", 1)[1].split("\n## ", 1)[0]


def test_install_passes_key_on_stdin_not_argv() -> None:
    code = _code(INSTALL)
    assert "--from-literal" not in code
    assert '"$OPENCODE_KEY"' not in code.replace('printf %s "$OPENCODE_KEY" |', "")
    assert re.search(
        r'printf %s "\$OPENCODE_KEY" \|[^\n]*--from-file=Authorization=/dev/stdin', code
    )


def test_install_creates_secret_without_client_side_apply() -> None:
    code = _code(INSTALL)
    assert "--dry-run" not in code
    assert re.search(r"delete secret \$SECRET [^\n]*--ignore-not-found", code)
    assert re.search(r"k create secret generic \$SECRET", code)


def test_check_greps_cannot_exit_silently() -> None:
    for line in _code(CHECK).splitlines():
        if "$(" in line and "grep" in line:
            assert "|| true" in line, line


def test_check_reads_main_checkout_env_and_fails_without_it() -> None:
    code = _code(CHECK)
    assert "--git-common-dir" in code
    assert re.search(r'\[ -f "\$ENV_FILE" \] \|\| fail', code)


def test_check_matches_openai_key_and_exempts_placeholder() -> None:
    code = _code(CHECK)
    assert "OPENAI_API_KEY" in code
    assert "kagent-tools-openai" in code


def test_check_reports_agent_workload_and_log_records_limit() -> None:
    code = _code(CHECK)
    for needle in ("workerPoolRef", "WorkerPool", "SandboxTemplate", "agent workload"):
        assert needle in code, needle
    assert "sandbox" in _section(LOG.read_text(), 14).lower()
    assert "process env" in _section(LOG.read_text(), 14)


def test_pinned_versions_records_proxy_image_digest() -> None:
    assert re.search(
        r"cr\.agentgateway\.dev/agentgateway:v1\.6\.0.*sha256:[0-9a-f]{64}", PINNED.read_text()
    )


def test_spike_log_section_14_names_sources_with_date() -> None:
    section = _section(LOG.read_text(), 14)
    assert "docs/sources.md" in section
    assert re.search(r"20\d\d-\d\d-\d\d", section)
    assert "byo-agentgateway" in section and "opencode.ai/docs/go" in section
