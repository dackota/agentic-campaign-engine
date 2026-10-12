"""Process settings from the environment: one loader for the API and the worker, and the
same loader for the fake Marketo. A missing variable fails at start with its name only."""

import dataclasses
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ace_engine.settings import Depth, Settings
from fake_marketo.app import MarketoConfig

ROOT = Path(__file__).resolve().parents[2]
PYTHONPATH = [
    "apps/engine",
    "apps/api",
    "apps/worker",
    "services/fakes",
    "services/render",
    "services/mcp",
]
# Values a reader could mistake for nothing else, so a leak is easy to spot.
CLIENT_SECRET = "sentinel-client-secret-5a1e"
WEBHOOK_SECRET = "sentinel-webhook-secret-77b3"
DB_PASSWORD = "sentinel-db-password-9c4d"

FULL_ENV = {
    "ACE_DEPTH": "live",
    "ACE_DATABASE_URL": "postgresql+psycopg://ace@postgres:5432/ace",
    "ACE_TEMPORAL_ADDRESS": "temporal:7233",
    "ACE_TEMPORAL_NAMESPACE": "ace-ns",
    "ACE_AGENT_URL": "http://agent:8080",
    "ACE_MARKETO_URL": "http://fake-marketo:8000",
    "ACE_MARKETO_CLIENT_ID": "ace-demo",
    "ACE_MARKETO_CLIENT_SECRET": CLIENT_SECRET,
    "ACE_MARKETO_WEBHOOK_SECRET": WEBHOOK_SECRET,
    "ACE_WORKFRONT_URL": "http://fake-workfront:8000",
    "ACE_WORKFRONT_CLIENT_ID": "ace-wf",
    "ACE_WORKFRONT_CLIENT_SECRET": "sentinel-wf-client-secret-5a1e",
    "ACE_WORKFRONT_WEBHOOK_SECRET": "sentinel-wf-webhook-secret-2f8d",
    "ACE_AGENT_TIMEOUT_SECONDS": "12.5",
    "ACE_MARKETO_TIMEOUT_SECONDS": "7",
    "ACE_OIDC_ISSUER": "http://dex.example/dex",
    "ACE_OIDC_CLIENT_ID": "other-client",
    "ACE_NOTIFY_TIMEOUT_SECONDS": "3",
    "ACE_SLACK_TOKEN": "sentinel-slack-token-31d2",
    "ACE_SLACK_CHANNEL": "#ace",
    "ACE_SLACK_URL": "http://fake-slack:8000",
    "ACE_ALERT_WEBHOOK_TOKEN": "sentinel-alert-token-6c3b",
    "ACE_WEB_URL": "http://web.example",
    "ACE_GOOGLE_CLIENT_ID": "gid",
    "ACE_GOOGLE_CLIENT_SECRET": "sentinel-google-secret-8e07",
    "ACE_GOOGLE_REFRESH_TOKEN": "sentinel-google-refresh-52aa",
    "ACE_GOOGLE_TOKEN_URL": "http://fake-google:8000/token",
    "ACE_GOOGLE_DOCS_URL": "http://fake-google:8000",
    "ACE_CMS_URL": "http://fake-cms:8000",
    "ACE_S3_URL": "http://fake-s3:8000",
    "ACE_S3_BUCKET": "other-bucket",
    "ACE_CONTENT_TIMEOUT_SECONDS": "9",
}


def settings_from_env(environ: dict[str, str], *, is_api: bool) -> Settings:
    assert importlib.util.find_spec("ace_engine.env"), "no env loader module ace_engine.env"
    loader = importlib.import_module("ace_engine.env").settings_from_env
    settings: Settings = loader(environ, is_api=is_api)
    return settings


def config_from_env(environ: dict[str, str]) -> MarketoConfig:
    module = importlib.import_module("fake_marketo.app")
    assert hasattr(module, "config_from_env"), "fake Marketo has no env loader"
    config: MarketoConfig = module.config_from_env(environ)
    return config


WORKER_ENV = {k: v for k, v in FULL_ENV.items() if not k.startswith("ACE_OIDC_")}


def test_api_loader_reads_every_settings_field() -> None:
    settings = settings_from_env(FULL_ENV, is_api=True)

    assert settings == Settings(
        depth=Depth.LIVE,
        database_url="postgresql+psycopg://ace@postgres:5432/ace",
        temporal_address="temporal:7233",
        temporal_namespace="ace-ns",
        agent_url="http://agent:8080",
        marketo_url="http://fake-marketo:8000",
        marketo_client_id="ace-demo",
        marketo_client_secret=CLIENT_SECRET,
        marketo_webhook_secret=WEBHOOK_SECRET,
        workfront_url="http://fake-workfront:8000",
        workfront_client_id="ace-wf",
        workfront_client_secret="sentinel-wf-client-secret-5a1e",
        workfront_webhook_secret="sentinel-wf-webhook-secret-2f8d",
        agent_timeout_seconds=12.5,
        marketo_timeout_seconds=7.0,
        oidc_issuer="http://dex.example/dex",
        oidc_client_id="other-client",
        notify_timeout_seconds=3.0,
        slack_token="sentinel-slack-token-31d2",
        slack_channel="#ace",
        slack_url="http://fake-slack:8000",
        web_url="http://web.example",
        google_client_id="gid",
        google_client_secret="sentinel-google-secret-8e07",
        google_refresh_token="sentinel-google-refresh-52aa",
        google_token_url="http://fake-google:8000/token",
        google_docs_url="http://fake-google:8000",
        cms_url="http://fake-cms:8000",
        s3_url="http://fake-s3:8000",
        s3_bucket="other-bucket",
        content_timeout_seconds=9.0,
        alert_webhook_token="sentinel-alert-token-6c3b",
    )
    # Every field differs from its default above, so a field the loader skipped would show.
    for f in dataclasses.fields(Settings):
        if f.default is not dataclasses.MISSING:
            assert getattr(settings, f.name) != f.default, f.name


def test_worker_loader_leaves_oidc_unset() -> None:
    settings = settings_from_env(FULL_ENV, is_api=False)

    assert settings.oidc_issuer == ""
    assert settings.oidc_client_id == "ace-web"
    assert settings.marketo_webhook_secret == WEBHOOK_SECRET


def test_api_needs_the_oidc_issuer() -> None:
    with pytest.raises(ValueError, match="ACE_OIDC_ISSUER"):
        settings_from_env(WORKER_ENV, is_api=True)


@pytest.mark.parametrize(
    "name",
    [
        "ACE_DATABASE_URL",
        "ACE_TEMPORAL_ADDRESS",
        "ACE_MARKETO_URL",
        "ACE_MARKETO_CLIENT_ID",
        "ACE_MARKETO_CLIENT_SECRET",
        "ACE_MARKETO_WEBHOOK_SECRET",
        "ACE_AGENT_URL",
    ],
)
def test_missing_required_variable_names_it_not_any_value(name: str) -> None:
    env = {k: v for k, v in FULL_ENV.items() if k != name}

    with pytest.raises(ValueError) as caught:
        settings_from_env(env, is_api=True)

    message = str(caught.value)
    assert name in message
    for secret in (CLIENT_SECRET, WEBHOOK_SECRET):
        assert secret not in message


def test_bad_number_names_the_variable() -> None:
    env = {**FULL_ENV, "ACE_AGENT_TIMEOUT_SECONDS": "soon"}

    with pytest.raises(ValueError, match="ACE_AGENT_TIMEOUT_SECONDS"):
        settings_from_env(env, is_api=True)


def test_database_password_joins_the_url_and_stays_out_of_repr() -> None:
    env = {**FULL_ENV, "ACE_DATABASE_PASSWORD": DB_PASSWORD}

    settings = settings_from_env(env, is_api=False)

    assert settings.database_url == f"postgresql+psycopg://ace:{DB_PASSWORD}@postgres:5432/ace"
    text = repr(settings)
    for secret in (DB_PASSWORD, CLIENT_SECRET, WEBHOOK_SECRET):
        assert secret not in text


def test_fake_marketo_config_comes_from_env() -> None:
    env = {**FULL_ENV, "ACE_MARKETO_WEBHOOK_URL": "http://api:8000/webhooks/marketo"}

    config = config_from_env(env)

    assert config.client_id == "ace-demo"
    assert config.client_secret == CLIENT_SECRET
    assert config.webhook_url == "http://api:8000/webhooks/marketo"
    assert config.webhook_secret == WEBHOOK_SECRET


def test_fake_marketo_missing_webhook_url_names_it() -> None:
    with pytest.raises(ValueError, match="ACE_MARKETO_WEBHOOK_URL"):
        config_from_env(FULL_ENV)


@pytest.mark.parametrize("module", ["campaign_api", "campaign_worker", "fake_marketo"])
def test_entrypoint_fails_at_start_naming_the_missing_variable(module: str) -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in PYTHONPATH),
        **{k: v for k, v in FULL_ENV.items() if k != "ACE_MARKETO_CLIENT_ID"},
        "ACE_MARKETO_WEBHOOK_URL": "http://api:8000/webhooks/marketo",
    }

    result = subprocess.run(
        [sys.executable, "-m", module], env=env, capture_output=True, text=True, timeout=60
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "ACE_MARKETO_CLIENT_ID" in output
    for secret in (CLIENT_SECRET, WEBHOOK_SECRET):
        assert secret not in output
