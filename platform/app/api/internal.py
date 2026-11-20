"""Calls from game servers. Not for players: every request is HMAC-signed with
the shared secret (header ``X-Signature``), and in production these paths are
only reachable on the internal network."""

import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from app.api.deps import SessionDep
from app.core.errors import ApiError
from app.services import seat_tokens
from app.services import tables as svc
from app.services.game_gateway import verify_internal

router = APIRouter(prefix="/internal", tags=["internal"])


class GameResult(BaseModel):
    # User ids, winner first.
    finishing_order: list[uuid.UUID]


@router.get("/seat-token-key", response_class=PlainTextResponse)
async def seat_token_key() -> str:
    """Public key the game server uses to check seat tokens."""
    return seat_tokens.public_key_pem()


@router.post("/games/{table_id}/result")
async def game_result(table_id: uuid.UUID, request: Request, session: SessionDep) -> dict[str, str]:
    raw = await request.body()
    if not verify_internal(raw, request.headers.get("x-signature")):
        raise ApiError(401, "bad_signature", "Invalid signature.")
    try:
        result = GameResult.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise ApiError(422, "bad_payload", "Malformed result.") from exc
    try:
        table = await svc.settle(session, table_id, result.finishing_order)
    except svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return {"status": table.status}
