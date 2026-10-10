"""Settings shared by the API and the worker. `ACE_DEPTH` picks fast or live depth."""

import os
from dataclasses import dataclass, field
from enum import StrEnum

WORKFLOW_NAME = "CampaignWorkflow"
TASK_QUEUE = "campaigns"
APPROVE_SIGNAL = "approve"
DEPTH_ENV = "ACE_DEPTH"
REQUIRED_SECRETS = ("marketo_client_id", "marketo_client_secret", "marketo_webhook_secret")


class Depth(StrEnum):
    FAST = "fast"
    LIVE = "live"

    @classmethod
    def parse(cls, value: str) -> "Depth":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"unknown depth {value!r}: use 'fast' or 'live'") from None

    @classmethod
    def from_env(cls) -> "Depth":
        return cls.parse(os.environ.get(DEPTH_ENV, cls.FAST))


@dataclass(frozen=True)
class Settings:
    depth: Depth
    # Holds the Postgres password on the cluster, so it stays out of the repr too.
    database_url: str = field(repr=False)
    temporal_address: str
    temporal_namespace: str
    agent_url: str
    marketo_url: str
    # Marketo's OAuth2 client credentials and the key its activity webhooks are signed
    # with. They come from the environment or a secret, never from code.
    marketo_client_id: str
    marketo_client_secret: str = field(repr=False)
    marketo_webhook_secret: str = field(repr=False)
    agent_timeout_seconds: float = 30.0
    marketo_timeout_seconds: float = 30.0
    # The OIDC provider (Dex) the Campaign API trusts, and the client id tokens are for.
    # The worker never checks tokens, so it leaves them unset.
    oidc_issuer: str = ""
    oidc_client_id: str = "ace-web"

    def __post_init__(self) -> None:
        # Fail when the worker starts, not on the first send after an approval.
        if not self.marketo_url.strip():
            raise ValueError("marketo_url is required: set it to the Marketo base URL")
        for name in REQUIRED_SECRETS:
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required: set it from the environment")
