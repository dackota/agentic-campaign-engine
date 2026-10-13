"""Judge agreement with a small hand-labeled set: measured through the Campaign API and
recorded in a file in git."""

import json
from pathlib import Path

import httpx
import pytest
from ace_engine import judge

from evals.agreement import FLOOR, LABELS_PATH, measure, write
from evals.runner import main
from tests.api.helpers import OWNER
from tests.harness.stack import Stack

GOOD = {
    "id": "good",
    "report": "Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.",
    "step": "landing_page",
    "acceptable": True,
}
BAD = {
    "id": "bad",
    "report": "Volt Typhoon targets edge routers\nOur agent gives 100% protection against it.",
    "step": "landing_page",
    "acceptable": False,
}


def test_floor_matches_the_judge_floor() -> None:
    assert FLOOR == judge.FLOOR


def test_agreement_counts_labels_the_judge_agrees_with(api: httpx.Client) -> None:
    agreement = measure(api, [GOOD, BAD], timeout=30)

    # The scripted judge gives every asset the top score, so it agrees only on the good one.
    assert (agreement.agreed, agreement.total) == (1, 2)
    assert agreement.rate == 0.5
    assert [(r["id"], r["agrees"]) for r in agreement.rows] == [("good", True), ("bad", False)]


def test_agreement_is_measured_and_written_to_a_file(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack.agent.script([])
    monkeypatch.setenv("ACE_API_TOKEN", stack.dex.token(OWNER))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps([GOOD, BAD]))
    out = tmp_path / "agreement.json"

    code = main(
        ["--api-url", stack.api_url, "--limit", "1", "--labels", str(labels)]
        + ["--agreement-out", str(out)]
    )

    saved = json.loads(out.read_text())
    assert code == 0
    assert (saved["agreed"], saved["total"], saved["rate"]) == (1, 2, 0.5)
    assert saved["floor"] == judge.FLOOR


def test_write_is_stable_json(tmp_path: Path) -> None:
    from evals.agreement import Agreement

    path = tmp_path / "a.json"
    write(path, Agreement(1, 2, [{"id": "x", "agrees": True}]), depth="fast")

    assert json.loads(path.read_text())["depth"] == "fast"
    assert path.read_text().endswith("\n")


def test_committed_agreement_file_records_the_labeled_set() -> None:
    labels = json.loads(LABELS_PATH.read_text())
    saved = json.loads((LABELS_PATH.parent / "judge_agreement.json").read_text())

    assert 4 <= len(labels) <= 12
    assert saved["total"] == len(labels)
    assert {r["id"] for r in saved["rows"]} == {label["id"] for label in labels}
    assert 0 <= saved["rate"] <= 1


def test_a_transport_failure_is_recorded_and_never_counts_as_agreement() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("api down", request=request)

    api = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(refuse))

    agreement = measure(api, [BAD], timeout=5)

    assert (agreement.agreed, agreement.total, agreement.errored) == (0, 0, 1)
    [row] = agreement.rows
    assert row["id"] == "bad"
    assert "api down" in row["error"]
    assert "agrees" not in row
