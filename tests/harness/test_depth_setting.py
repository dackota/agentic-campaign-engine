"""One setting picks fast or live depth for the seam 1 harness."""

import pytest
from ace_engine.settings import Depth

from tests.harness.stack import Stack


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


def test_live_depth_is_not_wired_yet() -> None:
    with pytest.raises(NotImplementedError):
        Stack(depth="live").start()
