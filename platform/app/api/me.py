import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, MailerDep, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import PayoutDestination, User
from app.services import referrals, rg
from app.services import tables as table_svc
from app.services.mailer import MailError
from app.services.payments import PaymentError, normalize_ke_phone

log = logging.getLogger(__name__)

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
async def update_me(
    body: ProfileUpdate, user: CurrentUser, session: SessionDep, mailer: MailerDep
) -> UserOut:
    if body.username is not None and body.username != user.username:
        # The game server knows players by name: no renames mid-game.
        if await table_svc.has_active_seat(session, user.id):
            raise ApiError(409, "seated", "You can change your name when you're not at a table.")
        taken = await session.scalar(select(User.id).where(User.username == body.username))
        if taken is not None:
            raise ApiError(409, "username_taken", "That username is taken.")
        user.username = body.username
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    phone_changed = False
    if body.phone is not None:
        try:
            phone = normalize_ke_phone(body.phone)
        except PaymentError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
        if phone != user.phone:
            phone_changed = user.phone is not None
            user.phone = phone
            if phone_changed:
                # Payouts only go to the profile number: retire old destinations
                # and pause withdrawals for a while (see withdraw.phone_change_hold_hours).
                user.phone_changed_at = utcnow()
                await session.execute(
                    update(PayoutDestination)
                    .where(PayoutDestination.user_id == user.id, PayoutDestination.phone != phone)
                    .values(is_active=False)
                )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(409, "username_taken", "That username is taken.") from exc
    if phone_changed:
        try:
            await mailer.send(
                user.email,
                "Your M-Pesa number was changed",
                f"The M-Pesa number on your Draely account was changed to "
                f"******{(user.phone or '')[-4:]}.\n\n"
                "Withdrawals are paused for a short while as a precaution. "
                "If this wasn't you, sign out of all devices and contact support right away.",
            )
        except MailError:
            log.warning("phone-change notice to %s failed", user.id)
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


class EmailInvitesIn(BaseModel):
    emails: list[EmailStr] = Field(min_length=1, max_length=20)
    message: str | None = Field(default=None, max_length=300)


@router.post("/invites")
async def invite_by_email(
    body: EmailInvitesIn, user: CurrentUser, session: SessionDep, mailer: MailerDep
) -> dict[str, Any]:
    """Invite people to Draely by email. The invite follows the email
    address: whenever it signs up, you get the referral and become friends.
    Emails that already have an account get a friend request instead; the
    answer is the same either way."""
    r = await referrals.invite_emails(
        session, mailer, user, [str(e) for e in body.emails], body.message
    )
    return {"invited": r.invited, "skipped": r.skipped}


@router.get("/invites")
async def my_sent_invites(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    """People you invited by email, and whether they have joined."""
    return await referrals.sent_invites(session, user)


# ---------------------------------------------------------- responsible gaming


class LimitIn(BaseModel):
    kind: Literal["deposit", "loss"]
    period: Literal["day", "week", "month"]
    amount_cents: int | None = Field(default=None, ge=0)  # null removes the limit


class SelfExcludeIn(BaseModel):
    period: Literal["24h", "7d", "30d", "6m", "permanent"]
    confirm: bool


class RealityCheckIn(BaseModel):
    minutes: int | None = Field(default=None, ge=15, le=240)


@router.get("/limits")
async def limits(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    out = await rg.overview(session, user)
    await session.commit()
    return out


@router.put("/limits")
async def set_limit(body: LimitIn, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Lowering a limit applies now; raising or removing it waits 24 h."""
    await rg.set_limit(session, user, body.kind, body.period, body.amount_cents)
    await session.commit()
    return await rg.overview(session, user)


@router.post("/self-exclude")
async def self_exclude(
    body: SelfExcludeIn, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Take a break from real-money play. It can't be shortened or undone."""
    if not body.confirm:
        raise ApiError(422, "confirm_required", "Confirm that you want to take a break.")
    until = rg.self_exclude(user, body.period)
    left = await table_svc.leave_all_open(session, user)
    await session.commit()
    return {"excluded_until": until.isoformat(), "tables_left": left}


@router.put("/reality-check")
async def reality_check(body: RealityCheckIn, user: CurrentUser, session: SessionDep) -> UserOut:
    user.reality_check_minutes = body.minutes
    await session.commit()
    return user_out(user)
