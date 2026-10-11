"""Slack and Google Docs are off unless their tokens are set; tokens come from the
environment and never show in a repr."""

from ace_engine.env import settings_from_env
from ace_engine.settings import Settings

BASE_ENV = {
    "ACE_DATABASE_URL": "postgresql+psycopg://ace@postgres:5432/ace",
    "ACE_TEMPORAL_ADDRESS": "temporal:7233",
    "ACE_TEMPORAL_NAMESPACE": "ace-ns",
    "ACE_AGENT_URL": "http://agent:8080",
    "ACE_DEPTH": "fast",
    "ACE_MARKETO_URL": "http://fake-marketo:8000",
    "ACE_MARKETO_CLIENT_ID": "ace-demo",
    "ACE_MARKETO_CLIENT_SECRET": "m-secret",
    "ACE_MARKETO_WEBHOOK_SECRET": "m-hook",
}
SLACK_TOKEN = "sentinel-slack-token-31d2"
GOOGLE_SECRET = "sentinel-google-secret-8e07"
GOOGLE_REFRESH = "sentinel-google-refresh-52aa"


def load(extra: dict[str, str]) -> Settings:
    return settings_from_env({**BASE_ENV, **extra}, is_api=False)


def test_integrations_default_off() -> None:
    settings = load({})

    assert settings.slack_enabled is False
    assert settings.google_enabled is False


def test_slack_is_on_with_a_token_and_a_channel() -> None:
    settings = load(
        {"ACE_SLACK_TOKEN": SLACK_TOKEN, "ACE_SLACK_CHANNEL": "#ace", "ACE_SLACK_URL": "http://s"}
    )

    assert settings.slack_enabled is True
    assert settings.slack_url == "http://s"
    assert SLACK_TOKEN not in repr(settings)


def test_a_slack_token_without_a_channel_leaves_slack_off() -> None:
    assert load({"ACE_SLACK_TOKEN": SLACK_TOKEN}).slack_enabled is False


def test_google_is_on_only_with_the_whole_oauth_triple() -> None:
    triple = {
        "ACE_GOOGLE_CLIENT_ID": "gid",
        "ACE_GOOGLE_CLIENT_SECRET": GOOGLE_SECRET,
        "ACE_GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH,
    }

    settings = load(triple)
    partial = load({k: v for k, v in triple.items() if k != "ACE_GOOGLE_REFRESH_TOKEN"})

    assert settings.google_enabled is True
    assert partial.google_enabled is False
    assert GOOGLE_SECRET not in repr(settings)
    assert GOOGLE_REFRESH not in repr(settings)
