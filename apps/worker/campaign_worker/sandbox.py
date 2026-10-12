"""Runs the program the design agent wrote in a standalone kagent sandbox and reads the two
social cards from its stdout. The sandbox has no network and no secret (see
docs/decisions/sandbox-design-agent.md); the program goes in encoded, the cards come out as
`CARD <n> <base64 of the svg>` lines, and the sandbox is deleted on every exit path."""

import asyncio
import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from ace_engine import contracts
from temporalio.exceptions import ApplicationError

SANDBOX_TEMPLATE = "ace-design-sandbox"
CARD_COUNT = 2
CARD_PREFIX = "CARD"
SANDBOX_FAILED = "SandboxFailed"
SANDBOX_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class SandboxConfig:
    api_url: str
    kagent_bin: str = "kagent"
    template: str = SANDBOX_TEMPLATE
    namespace: str = "kagent"
    timeout_seconds: float = SANDBOX_TIMEOUT_SECONDS


def _failed(reason: str) -> ApplicationError:
    return ApplicationError(reason, type=SANDBOX_FAILED, non_retryable=True)


async def _kagent(config: SandboxConfig, *args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        config.kagent_bin,
        "--api-url",
        config.api_url,
        "--gateway-url",
        config.api_url,
        "-n",
        config.namespace,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), config.timeout_seconds)
    except TimeoutError:
        process.kill()
        raise _failed(f"kagent {args[0]} {args[1]} timed out") from None
    if process.returncode != 0:
        raise _failed(f"kagent {args[0]} {args[1]} failed: {err.decode()[:200]}")
    return out.decode()


def _cards_from(stdout: str) -> dict[str, Any]:
    cards = []
    for n in range(1, CARD_COUNT + 1):
        line = next((ln for ln in stdout.splitlines() if ln.startswith(f"{CARD_PREFIX} {n} ")), "")
        try:
            svg = base64.b64decode(line.split(" ", 2)[2], validate=True).decode()
        except (IndexError, binascii.Error, UnicodeDecodeError):
            raise _failed(f"the program did not print card {n}") from None
        cards.append({"name": f"social-card-{n}.svg", "svg": svg})
    problems = contracts.violations({"cards": cards}, contracts.DESIGN_CARDS_SCHEMA)
    if problems:
        raise _failed("the program's cards break the contract: " + "; ".join(problems))
    return {"cards": cards}


async def run_design_program(program: str, config: SandboxConfig) -> dict[str, Any]:
    """Run `program` (a shell script) in a new sandbox; return the cards it printed."""
    created = json.loads(await _kagent(config, "sandbox", "create", config.template, "-o", "json"))
    sandbox_id = created["id"]
    try:
        encoded = base64.b64encode(program.encode()).decode()
        script = f"echo {encoded} | base64 -d > /tmp/make-cards.sh && sh /tmp/make-cards.sh"
        stdout = await _kagent(config, "sandbox", "exec", sandbox_id, "--", "sh", "-c", script)
        return _cards_from(stdout)
    finally:
        await _kagent(config, "sandbox", "delete", sandbox_id)
