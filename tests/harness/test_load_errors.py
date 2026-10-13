"""The load script's own error handling: an API it cannot reach, and replies it cannot read.
The Campaign API never sends a malformed reply, so these cases cannot be driven at seam 1;
they test the tool, like the other harness tool tests. Each lost run is counted with its
reason, and the numbers are always written."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.harness import load
from tests.harness.stack import free_port

# What a stand-in API answers to a campaign read: any JSON value.
type Reply = dict[str, object] | list[object]

CREATED = {"id": "c-1"}
GOOD_COST = {"cost_usd": 0.01, "steps": [{"cache_hit": False}]}


def _load(tmp_path: Path, api: httpx.Client | None, *extra: str) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "load.json"
    exit_code = load.main(["--campaigns", "2", "--out", str(out), "--timeout", "5", *extra], api)
    written: dict[str, Any] = json.loads(out.read_text())
    return exit_code, written


def _api_answering(campaign: Callable[[], Reply]) -> httpx.Client:
    """A stand-in API: creates answer 201, and every campaign read answers `campaign()`."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=CREATED)
        return httpx.Response(200, json=campaign())

    return httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handle))


def test_an_unreachable_api_loses_every_run_and_still_writes_the_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(load.TOKEN_ENV, "not-a-real-token")
    # Nothing listens on a port that was free a moment ago.
    dead_api = f"http://127.0.0.1:{free_port()}"

    exit_code, written = _load(tmp_path, None, "--api-url", dead_api)

    assert exit_code == 1
    assert written["lost"] == 2
    assert written["finished"] == 0
    assert all(r.startswith("ConnectError") for r in written["lost_reasons"])


@pytest.mark.parametrize(
    "campaign",
    [
        {"status": load.AWAITING, "cost": "x"},
        {"status": load.AWAITING, "cost": {"cost_usd": 0.01, "steps": ["x"]}},
        {"status": load.AWAITING, "cost": {"cost_usd": "x", "steps": []}},
        {"status": 7, "cost": GOOD_COST},
        {"cost": GOOD_COST},
        ["not", "an", "object"],
    ],
)
def test_a_reply_the_script_cannot_read_loses_the_run_with_a_reason(
    tmp_path: Path, campaign: Reply
) -> None:
    with _api_answering(lambda: campaign) as api:
        exit_code, written = _load(tmp_path, api)

    assert exit_code == 1
    assert written["lost"] == 2
    assert all(r.startswith("UnreadableReply") for r in written["lost_reasons"])


def test_a_good_reply_is_counted_as_finished(tmp_path: Path) -> None:
    campaign: Reply = {"status": load.AWAITING, "failure_reason": None, "cost": GOOD_COST}

    with _api_answering(lambda: campaign) as api:
        exit_code, written = _load(tmp_path, api)

    assert exit_code == 0
    assert written["finished"] == 2
    assert written["cost_per_campaign_usd"] == pytest.approx(0.01)


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_a_timeout_not_above_zero_is_refused(tmp_path: Path, timeout: str) -> None:
    with pytest.raises(SystemExit, match="--timeout must be above 0"):
        load.main(["--out", str(tmp_path / "load.json"), "--timeout", timeout], api=None)
