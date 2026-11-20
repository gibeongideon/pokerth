"""Process settings loaded from the environment.

Only infrastructure settings and secrets live here. Business settings
(limits, timeouts, rake, feature flags) go in the database-backed config
registry (Phase 1) so they can change without a redeploy.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLATFORM_", extra="ignore")

    env: Literal["local", "dev", "staging", "prod"] = "local"
    debug: bool = False
    public_base_url: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://platform:platform@localhost:5432/platform"
    redis_url: str = "redis://localhost:6379/0"

    # Paystack (secrets are never logged; empty secret disables payment routes)
    paystack_secret_key: SecretStr = SecretStr("")
    paystack_public_key: str = ""
    paystack_timeout_seconds: float = Field(default=15.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
