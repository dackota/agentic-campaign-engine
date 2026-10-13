"""Seam 1 at fast depth: each writer is told how long every field of its reply may be, with
the limits the eval's hard checks grade against, so a real model can stay within them."""

import httpx
from ace_engine.agent_roles import ROLES
from ace_engine.default_workflow import DEFAULT_WORKFLOW_NAME

from evals.checks import MAX_CHARS
from tests.api.helpers import AWAITING, create_on, read_events
from tests.harness.stack import Stack

REPORT = "Lighthouse botnet hijacks smart cameras\nOwners never changed the default password."
FIELDS = {
    "email_writer": ["subject", "preheader", "body", "call_to_action"],
    "landing_page": ["headline", "subheadline", "body", "call_to_action"],
    "social": ["text"],
    "one_pager": ["title", "summary", "bullets"],
}


def test_every_writer_is_told_the_length_limit_of_every_field(
    stack: Stack, api: httpx.Client
) -> None:
    campaign = create_on(api, DEFAULT_WORKFLOW_NAME, REPORT)
    assert read_events(api, campaign["id"])[-1]["status"] == AWAITING

    messages = [m for m in stack.agent.messages() if m.endswith(REPORT)]
    for step, fields in FIELDS.items():
        [sent] = [m for m in messages if m.startswith(ROLES[step].prompt) and "variant B" not in m]
        missing = [f for f in fields if f"{f}: at most {MAX_CHARS[f]} characters" not in sent]
        assert missing == [], f"{step} is not told the limit of {missing}"
