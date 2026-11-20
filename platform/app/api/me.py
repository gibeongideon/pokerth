from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import User
from app.services import referrals
from app.services.payments import PaymentError, normalize_ke_phone

router = APIRouter(prefix="/me", tags=["me"])

Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{3,20}$")]


class ProfileUpdate(BaseModel):
    username: Username | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = None


class AcceptTerms(BaseModel):
    confirm_over_18: bool
    accept_terms: bool


@router.get("")
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.patch("")
async def update_me(body: ProfileUpdate, user: CurrentUser, session: SessionDep) -> UserOut:
    if body.username is not None and body.username != user.username:
        taken = await session.scalar(select(User.id).where(User.username == body.username))
        if taken is not None:
            raise ApiError(409, "username_taken", "That username is taken.")
        user.username = body.username
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.phone is not None:
        try:
            user.phone = normalize_ke_phone(body.phone)
        except PaymentError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
    await session.commit()
    return user_out(user)


@router.post("/accept-terms")
async def accept_terms(body: AcceptTerms, user: CurrentUser, session: SessionDep) -> UserOut:
    if not (body.confirm_over_18 and body.accept_terms):
        raise ApiError(422, "terms_required", "You must be 18+ and accept the terms.")
    if user.terms_accepted_at is None:
        user.terms_accepted_at = utcnow()
        await session.commit()
    return user_out(user)


@router.get("/referral")
async def referral(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """The player's invite-a-friend code, link and earnings."""
    out = await referrals.summary(session, user)
    await session.commit()  # saves a newly created code
    return out
