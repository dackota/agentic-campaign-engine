"""What the scripted agent answers for a role, without a running agent: the canned outputs the
render, route and contract tests use as realistic step output."""

from typing import Any

from ace_engine.agent_roles import ROLES, message_for

from tests.harness.scripted_agent import default_reply
from tests.support.dag import REPORT


def scripted_output(step_id: str, report: str = REPORT, variant: int = 0) -> dict[str, Any]:
    """The output the scripted agent gives `step_id` for `report`: what a default run stores."""
    return default_reply(message_for(ROLES[step_id], report, {}, variant))
