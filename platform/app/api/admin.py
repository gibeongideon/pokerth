import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.errors import ApiError
from app.models import User
from app.services import config_registry as cfg

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
