"""At live depth each role is its own kagent Agent, reached under the controller's base URL;
at fast depth every role shares the scripted agent's one URL."""

from ace_engine.agent_roles import ROLES, agent_url_for
from ace_engine.settings import Depth

BASE = "http://kagent-controller.kagent:8083/agents/kagent"


def test_live_depth_reaches_the_agent_named_like_the_roles_template() -> None:
    assert agent_url_for(BASE, Depth.LIVE, ROLES["email_writer"]) == f"{BASE}/ace-email-writer"
    assert agent_url_for(BASE + "/", Depth.LIVE, ROLES["research"]) == f"{BASE}/ace-research"


def test_fast_depth_uses_the_one_url_for_every_role() -> None:
    for role in ROLES.values():
        assert agent_url_for("http://127.0.0.1:9", Depth.FAST, role) == "http://127.0.0.1:9"
