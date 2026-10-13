"""Seam 1 through the eval runner: the gate compares each report to the baseline in git and
fails on a drop past the margin. Fast depth, with the scripted agent."""

import json
import uuid
from pathlib import Path

import httpx
import pytest

from evals.gate import BASELINE_PATH, Baseline, compare, render_verdict
from evals.golden import GoldenReport, load_golden
from evals.runner import ReportResult, main, run_golden
from tests.api.helpers import OWNER
from tests.harness.stack import Stack

SAFE = GoldenReport(
    id="safe",
    report="Volt Typhoon targets edge routers\nActors exploit unpatched VPN appliances.",
    key_facts=("edge routers", "unpatched VPN appliances"),
)
MARGIN = 0.05


def baseline_of(quality: float, judge: float | None = 1.0) -> Baseline:
    return Baseline(margin=MARGIN, reports={"safe": {"quality": quality, "judge": judge}})


def result_with(facts_found: int, facts_total: int, judge: dict[str, int]) -> ReportResult:
    facts = {f"fact {n}": n < facts_found for n in range(facts_total)}
    return ReportResult("safe", "awaiting_approval", facts, [], judge_scores=judge)


def test_drop_past_the_margin_fails_with_a_readable_report() -> None:
    worse = result_with(1, 4, {"landing_page": 5})

    verdict = compare(baseline_of(1.0), [worse])

    text = render_verdict(verdict)
    assert not verdict.passed
    assert "FAIL safe: quality 0.40, baseline 1.00" in text
    assert "margin 0.05" in text


def test_drop_in_judge_scores_past_the_margin_fails() -> None:
    worse = result_with(2, 2, {"landing_page": 2, "social": 2})

    verdict = compare(baseline_of(1.0, judge=1.0), [worse])

    assert not verdict.passed
    assert "judge" in render_verdict(verdict)


def test_drop_within_the_margin_and_improvements_pass() -> None:
    within = result_with(1, 1, {"landing_page": 5})
    verdict = compare(baseline_of(1.0 + MARGIN - 0.001), [within])
    assert verdict.passed
    assert "PASS safe" in render_verdict(verdict)


def test_report_missing_from_the_baseline_fails_and_says_how_to_add_it() -> None:
    verdict = compare(Baseline(margin=MARGIN, reports={}), [result_with(1, 1, {})])

    assert not verdict.passed
    assert "--update-baseline" in render_verdict(verdict)


def test_committed_baseline_covers_every_golden_report() -> None:
    saved = json.loads(BASELINE_PATH.read_text())

    assert set(saved["reports"]) == {g.id for g in load_golden()}
    assert 0 < saved["margin"] < 1


def run_cli(stack: Stack, monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setenv("ACE_API_TOKEN", stack.dex.token(OWNER))
    return main(["--api-url", stack.api_url, "--limit", "2", *args])


def test_normal_run_leaves_the_baseline_unchanged_and_update_rewrites_it(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stack.agent.script([])
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"margin": MARGIN, "reports": {}}))
    before = path.read_text()

    gated = run_cli(stack, monkeypatch, "--baseline", str(path))
    assert (gated, path.read_text()) == (1, before)

    updated = run_cli(stack, monkeypatch, "--baseline", str(path), "--update-baseline")
    assert updated == 0
    assert path.read_text() != before
    assert len(json.loads(path.read_text())["reports"]) == 2

    again = path.read_text()
    code = run_cli(stack, monkeypatch, "--baseline", str(path))
    out = capsys.readouterr().out
    assert (code, path.read_text()) == (0, again)
    assert "PASS" in out


def test_weakened_prompt_fails_the_gate(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stack.agent.script([])
    path = tmp_path / "baseline.json"
    assert run_cli(stack, monkeypatch, "--baseline", str(path), "--update-baseline") == 0
    capsys.readouterr()

    # A weakened prompt is a new agent revision whose replies no longer carry the facts.
    stack.agent.set_revision(f"weakened-{uuid.uuid4().hex}")
    stack.agent.script(["Be vague."] * 400)
    try:
        code = run_cli(stack, monkeypatch, "--baseline", str(path))
    finally:
        stack.agent.script([])
        stack.agent.set_revision("1")

    out = capsys.readouterr().out
    assert code == 1
    assert "regressed" in out
    assert "baseline" in out


def test_second_run_of_unchanged_steps_makes_zero_model_calls(
    api: httpx.Client, stack: Stack
) -> None:
    entry = GoldenReport(SAFE.id, f"{SAFE.report}\ncase {uuid.uuid4().hex}", SAFE.key_facts)
    [first] = run_golden(api, [entry])
    calls_after_first = len(stack.agent.message_ids())

    [second] = run_golden(api, [entry])

    assert first.cache_hits == 0 < first.agent_steps
    assert len(stack.agent.message_ids()) == calls_after_first
    assert second.cache_hits == second.agent_steps > 0
    assert [a.checks for a in second.assets] == [a.checks for a in first.assets]
