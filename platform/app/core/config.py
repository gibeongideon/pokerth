"""Process settings loaded from the environment.

Only infrastructure settings and secrets live here. Business settings
(limits, timeouts, fees, FX rate, feature flags) live in the database-backed
registry in ``app/services/config_registry.py`` so admins can change them
without a redeploy.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-0123456789"  # noqa: S105 (refused outside local/dev)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLATFORM_", extra="ignore")

    env: Literal["local", "dev", "staging", "prod"] = "local"
    debug: bool = False
    # Where the player app lives; magic links and payment callbacks point here.
    public_base_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://platform:platform@localhost:55433/platform"
    redis_url: str = "redis://localhost:56379/0"

    # Auth
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    access_token_ttl_seconds: int = Field(default=900, gt=0)
    refresh_token_ttl_days: int = Field(default=30, gt=0)
    # OAuth client IDs (web, Android, iOS) accepted as Google ID-token audiences.
    google_client_ids: list[str] = []

    # Email (Mailpit locally)
    smtp_host: str = "localhost"
    smtp_port: int = 51025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False
    smtp_from: str = "Poker <no-reply@localhost>"

    # Paystack. An empty secret disables payment routes (503).
    paystack_secret_key: SecretStr = SecretStr("")
    paystack_public_key: str = ""
    paystack_base_url: str = "https://api.paystack.co"
    paystack_timeout_seconds: float = Field(default=15.0, gt=0)
    # Source IPs allowed to call the webhook; empty = no IP check (local only).
    paystack_webhook_ips: list[str] = []

    @model_validator(mode="after")
    def _no_dev_secrets_outside_local(self) -> "Settings":
        if self.env in ("staging", "prod"):
            secret = self.jwt_secret.get_secret_value()
            if secret == _DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError("PLATFORM_JWT_SECRET must be set (32+ chars) outside local/dev")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.env != "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
