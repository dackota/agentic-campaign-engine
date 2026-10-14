"""The stub activities of the workflow tests stand for exactly the activities the worker
registers: an activity added to the worker without a stub, or a stub for one that is gone,
fails here instead of in the middle of a workflow test."""

import inspect

import pytest
from campaign_worker.activities import Activities
from temporalio import activity

from tests.support import workflow_stubs
from tests.support.campaign_run import StubActivities
from tests.support.dag import DRAFT_APPROVE_PUBLISH


def _names(methods: list[object]) -> set[str]:
    names = set()
    for method in methods:
        definition = activity._Definition.from_callable(method)  # type: ignore[arg-type]
        assert definition is not None and definition.name is not None
        names.add(definition.name)
    return names


def test_the_stubs_are_the_activities_the_worker_registers() -> None:
    real = [f for _, f in inspect.getmembers(Activities, inspect.isfunction)]
    real_activities = [f for f in real if activity._Definition.from_callable(f) is not None]

    assert _names(list(StubActivities().activities)) == _names(real_activities)  # type: ignore[arg-type]


def test_a_run_that_neither_ends_nor_stops_fails_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_stubs, "WAIT_SECONDS", 0.5)

    # No cue approves the approval, so the run waits and never ends.
    with pytest.raises(AssertionError, match="neither finished nor stopped"):
        workflow_stubs.run_campaign(DRAFT_APPROVE_PUBLISH, workflow_stubs.StubActivities(), cues=[])
