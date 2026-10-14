"""The campaign workflow at the approval gate: nothing is sent while the run waits for a human,
approval sends once, and a send that cannot be trusted stops the run naming the reply."""

import asyncio
from datetime import timedelta

from temporalio.exceptions import ApplicationError

from tests.support.campaign_run import RECEIPT, StubActivities, running_campaign
from tests.support.dag import DRAFT_APPROVE_PUBLISH

AN_HOUR = timedelta(hours=1)
A_WEEK = timedelta(days=7)
PUBLISH = "publish"


def test_no_send_happens_without_approval() -> None:
    stubs = StubActivities()

    async def scenario() -> None:
        async with running_campaign(DRAFT_APPROVE_PUBLISH, stubs) as run:
            await run.until("open_approval")
            await run.sleep(A_WEEK)

    asyncio.run(scenario())

    assert stubs.count("open_approval") == 1
    assert stubs.count("send_email") == 0
    assert stubs.count("publish_content") == 0
    assert stubs.count("mark_sent") == 0
    assert stubs.count("finish_run") == 0


def test_approval_sends_once_and_the_run_ends_with_the_receipt() -> None:
    stubs = StubActivities()

    async def scenario() -> None:
        async with running_campaign(DRAFT_APPROVE_PUBLISH, stubs) as run:
            await run.until("open_approval")
            await run.sleep(AN_HOUR)
            assert stubs.count("send_email") == 0
            await run.approve()
            await run.finish()

    asyncio.run(scenario())

    assert stubs.count("send_email") == 1
    assert stubs.count("publish_content") == 1
    [(_, step_id, receipt)] = stubs.args_of("mark_sent")
    assert (step_id, receipt) == (PUBLISH, RECEIPT)
    assert stubs.count("finish_run") == 1
    # The approval is announced before the wait, and the send after it.
    names = [name for name, _ in stubs.calls]
    assert names.index("announce_approval") < names.index("send_email")
    assert names.index("send_email") < names.index("mark_sent") < names.index("announce_published")


def test_a_second_approval_signal_does_not_send_again() -> None:
    stubs = StubActivities()

    async def scenario() -> None:
        async with running_campaign(DRAFT_APPROVE_PUBLISH, stubs) as run:
            await run.until("open_approval")
            await run.approve()
            await run.approve()
            await run.finish()

    asyncio.run(scenario())

    assert stubs.count("send_email") == 1
    assert stubs.count("finish_run") == 1


def test_a_send_reply_that_cannot_be_trusted_fails_the_run_naming_it() -> None:
    def refuse(*_: object) -> object:
        raise ApplicationError(
            "Marketo reply has no receiptId: '{\"success\": true}'", non_retryable=True
        )

    stubs = StubActivities(send_email=refuse)

    async def scenario() -> None:
        async with running_campaign(DRAFT_APPROVE_PUBLISH, stubs) as run:
            await run.until("open_approval")
            await run.approve()
            await run.until("mark_failed")

    asyncio.run(scenario())

    [(_, step_id, reason)] = stubs.args_of("mark_failed")
    assert step_id == PUBLISH
    assert str(reason).startswith("step 'publish' failed: Marketo reply has no receiptId")
    # A reply that cannot be trusted is not retried, and nothing is recorded as sent.
    assert stubs.count("send_email") == 1
    assert stubs.count("publish_content") == 0
    assert stubs.count("mark_sent") == 0
    assert stubs.count("finish_run") == 0
