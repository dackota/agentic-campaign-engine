"""At live depth each role is its own kagent Agent, reached under the controller's base URL;
at fast depth every role shares the scripted agent's one URL."""

import pytest
from ace_engine.agent_roles import ROLES, agent_url_for
from ace_engine.settings import Depth

BASE = "http://kagent-controller.kagent:8083/agents/kagent"


def test_live_depth_reaches_the_agent_named_like_the_roles_template() -> None:
    assert agent_url_for(BASE, Depth.LIVE, ROLES["email_writer"]) == f"{BASE}/ace-email-writer"
    assert agent_url_for(BASE + "/", Depth.LIVE, ROLES["research"]) == f"{BASE}/ace-research"


def test_fast_depth_uses_the_one_url_for_every_role() -> None:
    for role in ROLES.values():
        assert agent_url_for("http://127.0.0.1:9", Depth.FAST, role) == "http://127.0.0.1:9"


def test_live_depth_reaches_the_agent_in_the_campaign_teams_namespace() -> None:
    url = agent_url_for(BASE, Depth.LIVE, ROLES["email_writer"], team="demand-gen")
    other = agent_url_for(BASE + "/", Depth.LIVE, ROLES["research"], team="product-marketing")

    controller = "http://kagent-controller.kagent:8083/agents"
    assert url == f"{controller}/team-demand-gen/ace-email-writer"
    assert other == f"{controller}/team-product-marketing/ace-research"


def test_fast_depth_ignores_the_team() -> None:
    url = agent_url_for("http://127.0.0.1:9", Depth.FAST, ROLES["research"], team="demand-gen")

    assert url == "http://127.0.0.1:9"


@pytest.mark.parametrize("team", ["", "../kagent", "Demand Gen", "a/b", "-x", "x" * 60])
def test_a_team_that_is_not_a_namespace_name_is_refused(team: str) -> None:
    with pytest.raises(ValueError, match="team"):
        agent_url_for(BASE, Depth.LIVE, ROLES["research"], team=team)
