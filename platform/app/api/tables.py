import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import ApiError
from app.models import GameTable, StakeTier, TableSeat
from app.services import config_registry as cfg
from app.services import payments as pay
from app.services import seat_tokens
from app.services import tables as svc
from app.services.game_gateway import GameGateway, get_gateway

router = APIRouter(tags=["tables"])
GatewayDep = Annotated[GameGateway, Depends(get_gateway)]


class JoinRequest(BaseModel):
    invite_code: str | None = None


class QuickPlayRequest(BaseModel):
    tier_id: int


class PrivateTableRequest(BaseModel):
    tier_id: int


def _err(exc: svc.TableError) -> ApiError:
    return ApiError(exc.status_code, exc.code, str(exc))


async def _view(session: SessionDep, table_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    table = await session.get(GameTable, table_id)
    assert table is not None
    return await svc.table_view(session, table, user_id)


@router.get("/lobby/tiers")
async def tiers(session: SessionDep) -> list[dict[str, Any]]:
    """Stake levels as players see them: one price, shown once."""
    rate = await cfg.get_decimal(session, "fx.usd_kes_rate")
    out = []
    for tier in (
        await session.scalars(
            select(StakeTier).where(StakeTier.enabled).order_by(StakeTier.sort_order, StakeTier.id)
        )
    ).all():
        price = await svc.price_for(session, tier)
        out.append(
            {
                "id": tier.id,
                "name": tier.name,
                "price_label": price.label,
                "buy_in_cents": price.buy_in,
                "fee_cents": price.fee,
                "excise_cents": price.excise,
                "total_cents": price.total,
                "total_kes_reference": pay.kes_reference(price.total, rate),
                "seats": tier.seats,
                "min_players": tier.min_players,
                "start_mode": tier.start_mode,
                "payout_bps": tier.payout_bps,
                "max_prize_pool_cents": price.buy_in * tier.seats,
            }
        )
    return out


@router.get("/lobby/tables")
async def lobby_tables(
    session: SessionDep, tier_id: int | None = Query(None)
) -> list[dict[str, Any]]:
    counts = (
        select(TableSeat.table_id, func.count().label("n"))
        .where(TableSeat.status.in_(("registered", "playing")))
        .group_by(TableSeat.table_id)
        .subquery()
    )
    q = (
        select(GameTable, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.table_id == GameTable.id)
        .where(GameTable.is_private.is_(False))
        .where(GameTable.status.in_(svc.ACTIVE_TABLE))
        .order_by(GameTable.created_at)
    )
    if tier_id is not None:
        q = q.where(GameTable.tier_id == tier_id)
    return [
        {
            "id": str(t.id),
            "name": t.config["name"],
            "price_label": t.config["price_label"],
            "status": t.status,
            "players": n,
            "seats_total": t.config["seats"],
            "scheduled_start_at": t.scheduled_start_at.isoformat()
            if t.scheduled_start_at
            else None,
        }
        for t, n in (await session.execute(q)).all()
    ]


@router.get("/tables/mine")
async def my_tables(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    tables = (
        await session.scalars(
            select(GameTable)
            .join(TableSeat, TableSeat.table_id == GameTable.id)
            .where(TableSeat.user_id == user.id, TableSeat.status.in_(svc.ACTIVE_SEAT))
            .where(GameTable.status.in_(svc.ACTIVE_TABLE))
        )
    ).all()
    return [await svc.table_view(session, t, user.id) for t in tables]


@router.get("/tables/{table_id}")
async def get_table(table_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    table = await session.get(GameTable, table_id)
    if table is None:
        raise ApiError(404, "not_found", "Table not found.")
    return await svc.table_view(session, table, user.id)


@router.post("/tables/{table_id}/join")
async def join(
    table_id: uuid.UUID,
    body: JoinRequest,
    user: CurrentUser,
    session: SessionDep,
    gateway: GatewayDep,
) -> dict[str, Any]:
    try:
        await svc.join(session, gateway, table_id, user, body.invite_code)
    except svc.TableError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await _view(session, table_id, user.id)


@router.post("/tables/{table_id}/leave")
async def leave(table_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    try:
        await svc.leave(session, table_id, user)
    except svc.TableError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await _view(session, table_id, user.id)


@router.post("/tables/{table_id}/ready")
async def ready(
    table_id: uuid.UUID, user: CurrentUser, session: SessionDep, gateway: GatewayDep
) -> dict[str, Any]:
    try:
        await svc.mark_ready(session, gateway, table_id, user)
    except svc.TableError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await _view(session, table_id, user.id)


@router.post("/lobby/quick-play")
async def quick_play(
    body: QuickPlayRequest, user: CurrentUser, session: SessionDep, gateway: GatewayDep
) -> dict[str, Any]:
    try:
        seat = await svc.quick_play(session, gateway, body.tier_id, user)
    except svc.TableError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await _view(session, seat.table_id, user.id)


@router.post("/tables/private", status_code=201)
async def create_private(
    body: PrivateTableRequest, user: CurrentUser, session: SessionDep, gateway: GatewayDep
) -> dict[str, Any]:
    """Open a private table for friends; share the invite code. The creator is seated."""
    tier = await session.get(StakeTier, body.tier_id)
    if tier is None or not tier.enabled or tier.start_mode != "when_full":
        raise ApiError(404, "not_found", "That stake level is not available.")
    try:
        table = await svc.open_table(session, tier, private=True, created_by=user.id)
        await svc.join(session, gateway, table.id, user, table.invite_code)
    except svc.TableError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await _view(session, table.id, user.id)


@router.get("/tables/{table_id}/seat-token")
async def seat_token(table_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """What the table client needs to connect to the game server."""
    table = await session.get(GameTable, table_id)
    seat = await session.scalar(
        select(TableSeat).where(TableSeat.table_id == table_id, TableSeat.user_id == user.id)
    )
    if table is None or seat is None or seat.status != "playing" or table.status != "running":
        raise ApiError(409, "not_playing", "You don't have a seat in a running game here.")
    assert table.game_ref is not None
    playing = await session.scalar(
        select(func.count())
        .select_from(TableSeat)
        .where(TableSeat.table_id == table.id, TableSeat.status == "playing")
    )
    token = seat_tokens.issue(
        user_id=user.id,
        username=user.username or "",
        table_id=table.id,
        game_ref=table.game_ref,
        table_cfg=svc.game_server_cfg(table, int(playing or 0)),
    )
    return {"token": token, "ws_url": table.ws_url, "game_ref": table.game_ref}
