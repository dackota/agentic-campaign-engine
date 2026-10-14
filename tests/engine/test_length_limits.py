"""Each writer is told how long every field of its reply may be, with the limits the eval's
hard checks grade against, so a real model can stay within them."""

import pytest
from ace_engine.agent_roles import ROLES, message_for

from evals.checks import MAX_CHARS

REPORT = "Lighthouse botnet hijacks smart cameras\nOwners never changed the default password."
FIELDS = {
    "email_writer": ["subject", "preheader", "body", "call_to_action"],
    "landing_page": ["headline", "subheadline", "body", "call_to_action"],
    "social": ["text"],
    "one_pager": ["title", "summary", "bullets"],
}


@pytest.mark.parametrize("step", sorted(FIELDS))
def test_every_writer_is_told_the_length_limit_of_every_field(step: str) -> None:
    message = message_for(ROLES[step], REPORT, {})

    missing = [f for f in FIELDS[step] if f"{f}: at most {MAX_CHARS[f]} characters" not in message]
    assert missing == [], f"{step} is not told the limit of {missing}"
