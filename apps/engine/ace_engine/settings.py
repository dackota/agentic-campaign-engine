"""Settings shared by the API and the worker. `ACE_DEPTH` picks fast or live depth."""

import os
from dataclasses import dataclass, field
from enum import StrEnum

WORKFLOW_NAME = "CampaignWorkflow"
TASK_QUEUE = "campaigns"
APPROVE_SIGNAL = "approve"
RETRY_SIGNAL = "retry_step"
RAISE_BUDGET_SIGNAL = "raise_budget"
DEPTH_ENV = "ACE_DEPTH"
REQUIRED_SECRETS = ("marketo_client_id", "marketo_client_secret", "marketo_webhook_secret")
WORKFRONT_SECRETS = (
    "workfront_client_id",
    "workfront_client_secret",
    "workfront_webhook_secret",
)


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
    # The Workfront-shaped fake, optional: with no URL, approved campaigns publish to
    # Marketo only. With a URL, its client credentials and webhook key are required.
    workfront_url: str = ""
    workfront_client_id: str = ""
    workfront_client_secret: str = field(default="", repr=False)
    workfront_webhook_secret: str = field(default="", repr=False)
    agent_timeout_seconds: float = 30.0
    marketo_timeout_seconds: float = 30.0
    notify_timeout_seconds: float = 10.0
    # The OIDC provider (Dex) the Campaign API trusts, and the client id tokens are for.
    # The worker never checks tokens, so it leaves them unset.
    oidc_issuer: str = ""
    oidc_client_id: str = "ace-web"
    # The CMS that gets the landing page and the S3 store that gets the assets. Both are
    # in-cluster stand-ins that need no credentials; a blank URL skips that target.
    cms_url: str = ""
    s3_url: str = ""
    s3_bucket: str = "ace-assets"
    content_timeout_seconds: float = 30.0
    # Slack and Google Docs are off unless their credentials are set. The tokens come from
    # the environment or a secret, never from code, and stay out of the repr.
    slack_token: str = field(default="", repr=False)
    slack_channel: str = ""
    slack_url: str = "https://slack.com/api"
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    google_refresh_token: str = field(default="", repr=False)
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_docs_url: str = "https://docs.googleapis.com"

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_token.strip() and self.slack_channel.strip())

    @property
    def google_enabled(self) -> bool:
        return all(
            v.strip()
            for v in (self.google_client_id, self.google_client_secret, self.google_refresh_token)
        )

    def __post_init__(self) -> None:
        # Fail when the worker starts, not on the first send after an approval.
        if not self.marketo_url.strip():
            raise ValueError("marketo_url is required: set it to the Marketo base URL")
        for name in REQUIRED_SECRETS:
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required: set it from the environment")
        if self.workfront_url.strip():
            for name in WORKFRONT_SECRETS:
                if not getattr(self, name).strip():
                    raise ValueError(f"{name} is required when workfront_url is set")

    @property
    def has_workfront(self) -> bool:
        return bool(self.workfront_url.strip())
