"""Settings shared by the API and the worker. `ACE_DEPTH` picks fast or live depth."""

import os
from dataclasses import dataclass
from enum import StrEnum

WORKFLOW_NAME = "CampaignWorkflow"
TASK_QUEUE = "campaigns"
DEPTH_ENV = "ACE_DEPTH"


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
    database_url: str
    temporal_address: str
    temporal_namespace: str
    agent_url: str
    agent_timeout_seconds: float = 30.0
