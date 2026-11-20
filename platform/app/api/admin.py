import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import GameTable, StakeTier, User
from app.services import config_registry as cfg
from app.services import tables as table_svc

router = APIRouter(prefix="/admin", tags=["admin"])


class SettingUpdate(BaseModel):
    value: Any


class KycTierUpdate(BaseModel):
    kyc_tier: int = Field(ge=0, le=2)


@router.get("/settings")
async def list_settings(_admin: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    return await cfg.all_settings(session)


@router.put("/settings/{key}")
async def update_setting(
    key: str, body: SettingUpdate, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    try:
        await cfg.set_value(session, key, body.value, admin.id)
    except cfg.SettingError as exc:
        await session.rollback()
        raise ApiError(422, "invalid_setting", str(exc)) from exc
    await session.commit()
    return next(s for s in await cfg.all_settings(session) if s["key"] == key)


@router.put("/users/{user_id}/kyc-tier")
async def set_kyc_tier(
    user_id: uuid.UUID, body: KycTierUpdate, _admin: AdminUser, session: SessionDep
) -> UserOut:
    """Manual KYC override until the Smile ID integration lands."""
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "User not found.")
    user.kyc_tier = body.kyc_tier
    await session.commit()
    return user_out(user)


# ------------------------------------------------------------- stake levels (D-016)


class StakeTierIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    buy_in_cents: int = Field(ge=0)
    fee_type: Literal["pct", "flat"] = "pct"
    fee_value: Decimal = Field(default=Decimal("0.5"), ge=0)
    fee_min_cents: int = Field(default=0, ge=0)
    fee_max_cents: int | None = Field(default=None, ge=0)
    seats: int = 6
    min_players: int = 2
    start_mode: Literal["when_full", "scheduled"] = "when_full"
    payout_bps: list[int] = [6500, 3500]
    starting_chips: int = Field(default=3000, gt=0)
    first_small_blind: int = Field(default=10, gt=0)
    blind_level_minutes: int = Field(default=5, gt=0)
    enabled: bool = True
    sort_order: int = 0


def _tier_out(t: StakeTier) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "buy_in_cents": t.buy_in_cents,
        "fee_type": t.fee_type,
        "fee_value": str(t.fee_value),
        "fee_min_cents": t.fee_min_cents,
        "fee_max_cents": t.fee_max_cents,
        "fee_cents": table_svc.compute_fee(t),
        "seats": t.seats,
        "min_players": t.min_players,
        "start_mode": t.start_mode,
        "payout_bps": t.payout_bps,
        "starting_chips": t.starting_chips,
        "first_small_blind": t.first_small_blind,
        "blind_level_minutes": t.blind_level_minutes,
        "enabled": t.enabled,
        "sort_order": t.sort_order,
    }


@router.get("/stake-tiers")
async def list_tiers(_admin: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.scalars(select(StakeTier).order_by(StakeTier.sort_order, StakeTier.id))
    return [_tier_out(t) for t in rows.all()]


@router.post("/stake-tiers", status_code=201)
async def create_tier(body: StakeTierIn, _admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    tier = StakeTier(**body.model_dump())
    try:
        table_svc.validate_tier(tier)
    except table_svc.TableError as exc:
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    session.add(tier)
    await session.commit()
    return _tier_out(tier)


@router.put("/stake-tiers/{tier_id}")
async def update_tier(
    tier_id: int, body: StakeTierIn, _admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Changes apply to tables opened from now on; open tables keep their copy."""
    tier = await session.get(StakeTier, tier_id)
    if tier is None:
        raise ApiError(404, "not_found", "Stake level not found.")
    for key, value in body.model_dump().items():
        setattr(tier, key, value)
    try:
        table_svc.validate_tier(tier)
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return _tier_out(tier)


class ScheduledTableIn(BaseModel):
    tier_id: int
    scheduled_start_at: datetime


@router.post("/tables", status_code=201)
async def schedule_table(
    body: ScheduledTableIn, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Open a table that starts at a set time (needs min_players by then)."""
    tier = await session.get(StakeTier, body.tier_id)
    if tier is None:
        raise ApiError(404, "not_found", "Stake level not found.")
    if body.scheduled_start_at.tzinfo is None or body.scheduled_start_at <= utcnow():
        raise ApiError(422, "bad_time", "Give a future start time with a timezone.")
    table = await table_svc.open_table(
        session, tier, scheduled_start_at=body.scheduled_start_at, created_by=admin.id
    )
    await session.commit()
    return await table_svc.table_view(session, table)


@router.post("/tables/{table_id}/cancel")
async def cancel_table(
    table_id: uuid.UUID, _admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    table = await session.scalar(
        select(GameTable).where(GameTable.id == table_id).with_for_update()
    )
    if table is None:
        raise ApiError(404, "not_found", "Table not found.")
    try:
        await table_svc.cancel(session, table, "admin")
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return await table_svc.table_view(session, table)
