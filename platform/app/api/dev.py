"""Local-only helpers for trying the platform without the game server or a
front end. ``main.py`` mounts this router only when PLATFORM_ENV=local.

- ``/dev/dashboard``: a page showing the lobby, tables and wallets, with buttons
  that act as the seeded demo players.
- ``/dev/simulate-result``: stands in for the game server finishing a game.
"""

import random
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.errors import ApiError
from app.core.security import create_access_token
from app.models import GameTable, LedgerAccount, TableSeat, User
from app.services import tables as svc
from app.services.game_gateway import GameGateway, get_gateway

router = APIRouter(prefix="/dev", tags=["dev (local only)"])
GatewayDep = Annotated[GameGateway, Depends(get_gateway)]
_DASHBOARD = Path(__file__).with_name("dev_dashboard.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return _DASHBOARD.read_text()


@router.post("/token/{username}")
async def token_for(username: str, session: SessionDep) -> dict[str, str]:
    """Act as a demo player (local only)."""
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        raise ApiError(404, "not_found", "No such user.")
    return {"access_token": create_access_token(user.id)}


@router.post("/tick")
async def tick(session: SessionDep, gateway: GatewayDep) -> dict[str, int]:
    counts = await svc.tick(session, gateway)
    await session.commit()
    return counts


@router.post("/tables/{table_id}/simulate-result")
async def simulate_result(table_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """Finish a running game with a random finishing order."""
    players = list(
        (
            await session.scalars(
                select(TableSeat.user_id).where(
                    TableSeat.table_id == table_id, TableSeat.status == "playing"
                )
            )
        ).all()
    )
    random.shuffle(players)
    try:
        table = await svc.settle(session, table_id, players)
    except svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return await svc.table_view(session, table)


@router.get("/state")
async def state(session: SessionDep) -> dict[str, Any]:
    tables = (
        await session.scalars(select(GameTable).order_by(GameTable.created_at.desc()).limit(12))
    ).all()
    accounts = (await session.scalars(select(LedgerAccount).order_by(LedgerAccount.code))).all()
    users = {u.id: u for u in (await session.scalars(select(User))).all()}
    wallets, house = [], []
    for a in accounts:
        if a.user_id is not None:
            u = users.get(a.user_id)
            wallets.append({"username": u.username if u else "?", "balance_cents": a.balance})
        elif not a.code.startswith("table:"):
            house.append({"account": a.code, "balance_cents": a.balance})
    return {
        "tables": [await svc.table_view(session, t) for t in tables],
        "wallets": sorted(wallets, key=lambda w: w["username"] or ""),
        "house": house,
        "players": sorted(u.username for u in users.values() if u.username),
    }
