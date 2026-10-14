"""The scripted agent's drafts read like finished copy: a fix round's request, the planted
markers and the role prompt never leak into what a writer hands back, and its email draft
meets the email contract."""

import json

import pytest
from ace_engine.agent_roles import ROLES, message_for
from ace_engine.brand_review import fix_message
from ace_engine.contracts import EMAIL_DRAFT_SCHEMA, violations

from tests.harness.scripted_agent import FLAG_ISSUE, FLAG_MARKER, default_reply
from tests.support.dag import REPORT
from tests.support.scripted_outputs import scripted_output

# "[agent:flag]" sends every draft back through the brand reviewer's fix round.
FLAGGED_REPORT = f"{REPORT}\n{FLAG_MARKER}"
NOT_COPY = ("brand reviewer sent", "Fix these issues", "[agent:", "You are the")
WRITERS = ("email_writer", "landing_page", "social", "one_pager")


@pytest.mark.parametrize("step", WRITERS)
@pytest.mark.parametrize("variant", [0, 1])
def test_a_draft_sent_back_for_fixes_holds_only_finished_copy(step: str, variant: int) -> None:
    role = ROLES[step]
    prompt = fix_message(message_for(role, FLAGGED_REPORT, {}, variant), [FLAG_ISSUE])

    copy = json.dumps(default_reply(prompt))

    for leaked in NOT_COPY:
        assert leaked not in copy
    assert "Volt Typhoon" in copy


def test_the_email_draft_meets_the_email_contract() -> None:
    assert violations(scripted_output("email_writer"), EMAIL_DRAFT_SCHEMA) == []
