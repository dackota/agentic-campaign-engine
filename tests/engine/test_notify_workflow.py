"""When the workflow tells Slack and Google, on Temporal's time-skipping server with stub
activities: it asks for approval before it waits for one, and tells of the publish after the
send is recorded, with the receipt. A notice that fails never fails the run."""

import pytest

from tests.support.dag import DRAFT_APPROVE_PUBLISH, GOOD_DRAFT
from tests.support.workflow_stubs import StubActivities, run_campaign

RECEIPT = "receipt-42"
DRAFTS = [GOOD_DRAFT, {**GOOD_DRAFT, "subject": "Another subject"}]


def _run(failing: frozenset[str] = frozenset()) -> StubActivities:
    stubs = StubActivities(agent_outputs={"draft": DRAFTS}, receipt=RECEIPT, failing=failing)
    return run_campaign(DRAFT_APPROVE_PUBLISH, stubs)


def test_slack_is_asked_for_approval_before_the_run_waits_for_one() -> None:
    stubs = _run()

    names = stubs.names()
    assert names.index("open_approval") < names.index("announce_approval")
    assert names.index("announce_approval") < names.index("mark_step", names.index("open_approval"))
    [approval] = stubs.called("announce_approval")
    assert len(approval) == 1  # the campaign id


def test_the_publish_notice_follows_the_recorded_send_and_carries_the_receipt() -> None:
    stubs = _run()

    names = stubs.names()
    assert names.index("send_email") < names.index("mark_sent") < names.index("announce_published")
    [mark] = stubs.called("mark_sent")
    [published] = stubs.called("announce_published")
    assert mark[2] == RECEIPT
    assert published[1] == RECEIPT
    assert names[-1] == "finish_run"


@pytest.mark.parametrize("failing", ["announce_approval", "announce_published"])
def test_a_notice_that_fails_never_fails_the_run(failing: str) -> None:
    stubs = _run(frozenset({failing}))

    assert stubs.called("mark_failed") == []
    assert stubs.names()[-1] == "finish_run"
    assert len(stubs.called(failing)) == 1  # one try, no retries
