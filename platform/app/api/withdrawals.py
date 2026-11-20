import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, MailerDep, PaystackDep, SessionDep
from app.core.errors import ApiError
from app.models import PayoutDestination, Withdrawal
from app.services import payouts
from app.services.mailer import MailError
from app.services.payments import PaymentError

router = APIRouter(prefix="/wallet", tags=["withdrawals"])


class DestinationIn(BaseModel):
    phone: str


class WithdrawalIn(BaseModel):
    destination_id: uuid.UUID
    amount_usd_cents: int = Field(gt=0)


class ConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


def _err(exc: PaymentError) -> ApiError:
    return ApiError(exc.status_code, exc.code, str(exc))


@router.get("/payout-destinations")
async def destinations(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(PayoutDestination).where(
            PayoutDestination.user_id == user.id, PayoutDestination.is_active
        )
    )
    return [
        {"id": str(d.id), "kind": d.kind, "phone": d.phone, "account_name": d.account_name}
        for d in rows.all()
    ]


@router.post("/payout-destinations", status_code=201)
async def add_destination(
    body: DestinationIn, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    try:
        d = await payouts.add_destination(session, user, body.phone)
    except PaymentError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return {"id": str(d.id), "kind": d.kind, "phone": d.phone, "account_name": d.account_name}


@router.get("/withdrawals/quote")
async def quote(
    session: SessionDep, _user: CurrentUser, amount_usd_cents: int = Query(gt=0)
) -> dict[str, Any]:
    try:
        q = await payouts.quote(session, amount_usd_cents)
    except PaymentError as exc:
        raise _err(exc) from exc
    return {**q, "fx_rate": str(q["fx_rate"])}


@router.get("/withdrawals")
async def list_withdrawals(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Withdrawal)
        .where(Withdrawal.user_id == user.id)
        .order_by(Withdrawal.created_at.desc())
        .limit(50)
    )
    return [payouts.view(w) for w in rows.all()]


@router.post("/withdrawals", status_code=201)
async def request_withdrawal(
    body: WithdrawalIn,
    user: CurrentUser,
    session: SessionDep,
    mailer: MailerDep,
    paystack: PaystackDep,
) -> dict[str, Any]:
    """Starts a withdrawal. Usually answers ``awaiting_confirmation``: the
    player then sends the emailed code to ``/confirm``."""
    try:
        w = await payouts.request(
            session,
            mailer,
            user,
            destination_id=body.destination_id,
            usd_cents=body.amount_usd_cents,
        )
    except PaymentError as exc:
        await session.rollback()
        raise _err(exc) from exc
    except MailError as exc:
        # The withdrawal row exists but no money moved; it expires unconfirmed.
        raise ApiError(503, "email_unavailable", "We couldn't email your code. Try again.") from exc
    await session.commit()
    if w.status == "approved":
        w = await payouts.send(session, paystack, w.reference)
        await session.commit()
    return payouts.view(w)


@router.post("/withdrawals/{reference}/confirm")
async def confirm(
    reference: str, body: ConfirmIn, user: CurrentUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    try:
        w = await payouts.confirm(session, user, reference, body.code)
    except PaymentError as exc:
        await session.commit()  # keep attempt counts / expiry
        raise _err(exc) from exc
    await session.commit()
    if w.status == "approved":
        w = await payouts.send(session, paystack, w.reference)
        await session.commit()
    return payouts.view(w)


@router.post("/withdrawals/{reference}/cancel")
async def cancel(reference: str, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    try:
        w = await payouts.cancel(session, user, reference)
    except PaymentError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return payouts.view(w)
