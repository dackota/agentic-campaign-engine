"""The stub activities of the workflow tests stand for the activities the worker registers:
an activity added to the worker without a stub, a stub for one that is gone, or a stub that
takes other parameters than the real one fails here instead of in the middle of a workflow
test. Three stub classes exist (tests/support/campaign_run.py, run_stubs.py and
workflow_stubs.py); each is checked."""

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from campaign_worker.activities import Activities
from temporalio import activity

from tests.support import run_stubs, workflow_stubs
from tests.support.campaign_run import StubActivities
from tests.support.dag import DRAFT_APPROVE_PUBLISH


def _name(method: Callable[..., Any]) -> str:
    definition = activity._Definition.from_callable(method)
    assert definition is not None and definition.name is not None
    return definition.name


def _real_activities() -> dict[str, Callable[..., Any]]:
    methods = [f for _, f in inspect.getmembers(Activities, inspect.isfunction)]
    return {_name(f): f for f in methods if activity._Definition.from_callable(f) is not None}


def _parameters(method: Callable[..., Any]) -> list[tuple[str, object, object]]:
    """Each parameter's name, annotation and default; `self` is not one."""
    function = getattr(method, "__func__", method)
    return [
        (p.name, p.annotation, p.default)
        for p in inspect.signature(function).parameters.values()
        if p.name != "self"
    ]


def _stubs() -> dict[str, dict[str, Callable[..., Any]]]:
    """Every stub class's activities by name, and whether it must have all the real ones."""
    return {
        "campaign_run": {_name(m): m for m in StubActivities().activities},
        "run_stubs": {_name(m): m for m in run_stubs.StubActivities().activities()},
        "workflow_stubs": {_name(m): m for m in workflow_stubs.StubActivities().all()},
    }


def test_the_campaign_run_stubs_are_the_activities_the_worker_registers() -> None:
    assert set(_stubs()["campaign_run"]) == set(_real_activities())


@pytest.mark.parametrize("stub", ["campaign_run", "run_stubs", "workflow_stubs"])
def test_a_stub_activity_is_a_real_one_with_the_same_parameters(stub: str) -> None:
    real = _real_activities()
    stubbed = _stubs()[stub]

    assert set(stubbed) <= set(real)
    assert {name: _parameters(m) for name, m in stubbed.items()} == {
        name: _parameters(real[name]) for name in stubbed
    }


def test_a_run_that_neither_ends_nor_stops_fails_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_stubs, "WAIT_SECONDS", 0.5)

    # No cue approves the approval, so the run waits and never ends.
    with pytest.raises(AssertionError, match="neither finished nor stopped"):
        workflow_stubs.run_campaign(DRAFT_APPROVE_PUBLISH, workflow_stubs.StubActivities(), cues=[])
