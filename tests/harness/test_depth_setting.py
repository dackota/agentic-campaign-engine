"""One setting picks fast or live depth for the seam 1 harness."""

import pytest
from ace_engine.settings import Depth

from tests.harness.stack import KAGENT_AGENTS_PATH, kagent_port_forward_command


def test_fast_is_default_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACE_DEPTH", raising=False)
    assert Depth.from_env() is Depth.FAST


def test_depth_is_read_from_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACE_DEPTH", "live")
    assert Depth.from_env() is Depth.LIVE


def test_unknown_depth_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACE_DEPTH", "medium")
    with pytest.raises(ValueError, match="medium"):
        Depth.from_env()


def test_live_depth_reaches_kagent_on_the_ace_cluster_only() -> None:
    command = kagent_port_forward_command(18083)

    assert command[:3] == ["kubectl", "--context", "k3d-ace"]
    assert "svc/kagent-controller" in command and "18083:8083" in command
    assert "k3d-ace-spike" not in command
    assert KAGENT_AGENTS_PATH == "/agents/kagent"
