"""Settings for a test that runs no stack: every URL points at nothing, every secret is a dummy."""

import dataclasses
from typing import Any, cast

from ace_engine.settings import Depth, Settings

DUMMY_SETTINGS = Settings(
    depth=Depth.FAST,
    database_url="sqlite://",
    temporal_address="temporal.invalid:7233",
    temporal_namespace="default",
    agent_url="http://agent.invalid",
    marketo_url="http://marketo.invalid",
    marketo_client_id="marketo-id",
    marketo_client_secret="marketo-secret",
    marketo_webhook_secret="marketo-webhook-secret",
    oidc_issuer="http://dex.invalid/dex",
)


def unit_settings(**overrides: object) -> Settings:
    return dataclasses.replace(DUMMY_SETTINGS, **cast("dict[str, Any]", overrides))
