"""Measure prompt caching on k3d-ace: how many input tokens the model provider served from
its cache, for calls that open with an uncached prompt and for repeats of one prompt.

It sends the email writer Agent (through the kagent controller, then agentgateway, then
OpenCode Go) long prompts over A2A, then reads the gateway's access log for those calls.
The log line carries token counts and timing only; this script prints no other field of
it, and no key is read or printed. Every kubectl call names the context.

    kubectl --context k3d-ace port-forward -n kagent svc/kagent-controller 18083:8083 &
    uv run python scripts/measure_prompt_cache.py http://127.0.0.1:18083/agents/kagent/ace-email-writer
"""

import json
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx

CONTEXT = "k3d-ace"
GATEWAY_NAMESPACE = "agentgateway-system"
CALLS_PER_GROUP = 3
REPORT_LINES = 120
MIN_PROMPT_TOKENS = 2000
SETTLE_SECONDS = 3
CALL_TIMEOUT_SECONDS = 170
FIELDS = {
    "input": r"gen_ai\.usage\.input_tokens=(\d+)",
    "cached": r"gen_ai\.usage\.cache_read\.input_tokens=(\d+)",
    "output": r"gen_ai\.usage\.output_tokens=(\d+)",
    "ttft_s": r"agw\.ai\.time_to_first_token=([\d.]+)",
}


def prompt(salt: str) -> str:
    report = "\n".join(
        f"Line {i}: {salt} actors exploit unpatched edge VPN appliance number {i} to reach "
        "domain controllers."
        for i in range(REPORT_LINES)
    )
    return (
        "You are the email writer. Turn the threat report into a marketing email. Reply with "
        "only JSON that has the keys subject, preheader, body, call_to_action.\n\n"
        f"THREAT REPORT:\n{report}"
    )


def send(url: str, text: str) -> None:
    message_id = str(uuid.uuid4())
    body = {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            }
        },
    }
    response = httpx.post(
        url, json=body, headers={"A2A-Version": "1.0"}, timeout=CALL_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    if "error" in response.json():
        raise SystemExit("the agent answered with an error")


def gateway_calls(since: datetime) -> list[dict[str, float]]:
    logs = subprocess.run(
        [
            "kubectl", "--context", CONTEXT, "-n", GATEWAY_NAMESPACE, "logs",
            "deploy/agentgateway-proxy", f"--since-time={since:%Y-%m-%dT%H:%M:%SZ}",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    calls: list[dict[str, float]] = []
    for line in logs.splitlines():
        found = {k: re.search(p, line) for k, p in FIELDS.items()}
        if all(found.values()):
            call = {k: float(m.group(1)) for k, m in found.items() if m}
            if call["input"] >= MIN_PROMPT_TOKENS:
                calls.append(call)
    return calls


def main(url: str) -> None:
    started = datetime.now(UTC)
    for n in range(CALLS_PER_GROUP):
        send(url, prompt(f"cold-{uuid.uuid4().hex}-{n}"))
    time.sleep(SETTLE_SECONDS)
    cold_end = len(gateway_calls(started))
    repeated = prompt(f"warm-{uuid.uuid4().hex}")
    for _ in range(CALLS_PER_GROUP + 1):
        send(url, repeated)
    time.sleep(SETTLE_SECONDS)
    calls = gateway_calls(started)
    result = {
        "unique_prompts": calls[:cold_end],
        "repeated_prompt": calls[cold_end:],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
