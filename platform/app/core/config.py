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
_DEV_GAME_SECRET = "dev-only-insecure-game-secret"  # noqa: S105 (refused outside local/dev)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLATFORM_", extra="ignore")

    env: Literal["local", "dev", "staging", "prod"] = "local"
    debug: bool = False
    # Where the player app lives; magic links and payment callbacks point here.
    public_base_url: str = "http://localhost:5173"
    # The Capacitor apps load from https://localhost (Android) and capacitor://localhost (iOS).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://localhost",
        "capacitor://localhost",
    ]
    # Path the API is served under on the app's origin ("/api" behind Vite/Caddy);
    # the refresh cookie is scoped to <prefix>/auth so the browser sends it there.
    cookie_path_prefix: str = ""

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

    # Game server integration (D-009)
    # Ed25519 private key (PEM) that signs seat tokens. Empty in local = a key
    # derived from jwt_secret, so every local process agrees.
    seat_token_private_key: SecretStr = SecretStr("")
    seat_token_ttl_seconds: int = Field(default=300, gt=0)
    # Shared secret for HMAC-signed calls between platform and game server.
    game_internal_secret: SecretStr = SecretStr(_DEV_GAME_SECRET)
    # Where clients connect when no real game server is wired (local stand-in).
    game_ws_url: str = "ws://localhost:7233"

    @model_validator(mode="after")
    def _no_dev_secrets_outside_local(self) -> "Settings":
        if self.env in ("staging", "prod"):
            secret = self.jwt_secret.get_secret_value()
            if secret == _DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError("PLATFORM_JWT_SECRET must be set (32+ chars) outside local/dev")
            if self.game_internal_secret.get_secret_value() == _DEV_GAME_SECRET:
                raise ValueError("PLATFORM_GAME_INTERNAL_SECRET must be set outside local/dev")
            if not self.seat_token_private_key.get_secret_value():
                raise ValueError("PLATFORM_SEAT_TOKEN_PRIVATE_KEY must be set outside local/dev")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.env != "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
