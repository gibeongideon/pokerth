"""How the platform talks to game servers (D-009).

``LocalGateway`` is a stand-in until the C++ server's managed mode exists
(Phase 2b): it hands out a game reference and the configured WebSocket URL
without contacting anything. Results then come from the dev "simulate" endpoint.
The real gateway will POST the game to the server's internal HTTP API.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings


@dataclass(frozen=True)
class GamePlacement:
    game_ref: str
    ws_url: str


class GameGateway(Protocol):
    async def create_game(
        self, table_id: uuid.UUID, config: dict[str, Any], players: list[dict[str, str]]
    ) -> GamePlacement: ...


class LocalGateway:
    async def create_game(
        self, table_id: uuid.UUID, config: dict[str, Any], players: list[dict[str, str]]
    ) -> GamePlacement:
        return GamePlacement(game_ref=f"local-{table_id}", ws_url=get_settings().game_ws_url)


def get_gateway() -> GameGateway:
    return LocalGateway()


def sign_internal(body: bytes) -> str:
    """HMAC-SHA256 used on every call between platform and game server."""
    secret = get_settings().game_internal_secret.get_secret_value()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_internal(body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign_internal(body), signature or "")
