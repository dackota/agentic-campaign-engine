"""Shared readers for the S1 gateway files: manifests, scripts, spike log."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "manifests/spike"
SCRIPTS = ROOT / "scripts/spike"

GATEWAY = SPIKE / "gateway.yaml"
ANTHROPIC = SPIKE / "gateway-anthropic.yaml"
FAILOVER_TEST = SPIKE / "gateway-failover-test.yaml"
AGENT = SPIKE / "agent.yaml"
MOCK = SPIKE / "mock-llm.yaml"
CHECK = SCRIPTS / "gateway-check.sh"
FAILOVER_CHECK = SCRIPTS / "gateway-failover-check.sh"
INSTALL = SCRIPTS / "gateway-install.sh"
LOG = ROOT / "docs/spike-log.md"
ENV_EXAMPLE = ROOT / ".env.example"

# Every gateway file a key could leak into.
KEY_SCAN_PATHS = (GATEWAY, ANTHROPIC, FAILOVER_TEST, AGENT, CHECK, FAILOVER_CHECK, INSTALL)


def yaml_docs(path: Path) -> list[dict[str, Any]]:
    """The non-empty YAML documents in a manifest."""
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def script_code(path: Path) -> str:
    """The script without its comment lines."""
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )
