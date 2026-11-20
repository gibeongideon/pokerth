"""Seat tokens (D-009): short-lived Ed25519-signed JWTs that let one player
take one seat in one game. The game server verifies them with the public key
from ``GET /internal/seat-token-key``; it never needs the private key."""

import hashlib
import uuid
from datetime import timedelta
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import get_settings
from app.core.security import utcnow

ISSUER = "platform"
AUDIENCE = "game-server"


@lru_cache
def _private_key() -> Ed25519PrivateKey:
    settings = get_settings()
    pem = settings.seat_token_private_key.get_secret_value()
    if pem:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("PLATFORM_SEAT_TOKEN_PRIVATE_KEY must be an Ed25519 key")
        return key
    # Local/dev only (config refuses this in staging/prod): derive a stable key.
    seed = hashlib.sha256(b"seat-token:" + settings.jwt_secret.get_secret_value().encode())
    return Ed25519PrivateKey.from_private_bytes(seed.digest())


def public_key_pem() -> str:
    return (
        _private_key()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def issue(*, user_id: uuid.UUID, username: str, table_id: uuid.UUID, game_ref: str) -> str:
    now = utcnow()
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "name": username,
        "tbl": str(table_id),
        "game": game_ref,
        "iat": now,
        "exp": now + timedelta(seconds=get_settings().seat_token_ttl_seconds),
    }
    return jwt.encode(claims, _private_key(), algorithm="EdDSA")
