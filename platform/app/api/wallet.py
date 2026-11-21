from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, PaystackDep, SessionDep
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import Deposit, JournalTransaction, LedgerAccount, LedgerEntry
from app.services import config_registry as cfg
from app.services import ledger
from app.services import payments as pay
from app.services import play as play_svc

router = APIRouter(prefix="/wallet", tags=["wallet"])

# A pending deposit is re-checked with Paystack when polled after this long.
_POLL_VERIFY_AFTER = timedelta(seconds=10)


class DepositRequest(BaseModel):
    channel: Literal["card", "mpesa"]
    amount_usd_cents: int = Field(gt=0)
    phone: str | None = None
    # Username or email of the player to fund; omit to fund yourself.
    recipient: str | None = None


class TransferRequest(BaseModel):
    recipient: str
    amount_usd_cents: int = Field(gt=0)
    # Client-generated (e.g. a UUID) so a retried request never sends twice.
    idempotency_key: str = Field(min_length=8, max_length=64)
    note: str | None = Field(default=None, max_length=140)


def _payment_error(exc: pay.PaymentError) -> ApiError:
    return ApiError(exc.status_code, exc.code, str(exc))


@router.get("")
async def wallet(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    cents = await ledger.balance(session, ledger.user_available(user.id))
    rate = await cfg.get_decimal(session, "fx.usd_kes_rate")
    return {
        "available_usd_cents": cents,
        "kes_reference": pay.kes_reference(cents, rate),
        "usd_kes_rate": str(rate),
        "real_money_enabled": await cfg.get_bool(session, "real_money_enabled"),
    }


@router.get("/play")
async def demo_money(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Play money for free tables (never real money)."""
    out = await play_svc.status(session, user)
    await session.commit()  # saves the starting grant
    return out


@router.post("/play/refill")
async def refill_demo_money(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Top play money back up - only when it has run out, limited per day."""
    try:
        await play_svc.refill(session, user)
    except play_svc.PlayError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    out = await play_svc.status(session, user)
    await session.commit()
    return out


@router.get("/history")
async def history(
    user: CurrentUser, session: SessionDep, limit: int = Query(50, ge=1, le=200)
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                LedgerEntry.amount,
                JournalTransaction.kind,
                JournalTransaction.memo,
                JournalTransaction.created_at,
                JournalTransaction.id,
            )
            .join(JournalTransaction, JournalTransaction.id == LedgerEntry.transaction_id)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerAccount.code == ledger.user_available(user.id))
            .order_by(JournalTransaction.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "transaction_id": r.id,
            "kind": r.kind,
            "amount_usd_cents": r.amount,
            "memo": r.memo,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/deposits/quote")
async def deposit_quote(
    session: SessionDep,
    _user: CurrentUser,
    channel: Literal["card", "mpesa"],
    amount_usd_cents: int = Query(gt=0),
) -> dict[str, Any]:
    """Show exactly what will be charged before the user confirms."""
    try:
        q = await pay.quote(session, channel, amount_usd_cents)
    except pay.PaymentError as exc:
        raise _payment_error(exc) from exc
    return {
        "channel": q.channel,
        "credit_usd_cents": q.credit_usd_cents,
        "charge_currency": q.charge_currency,
        "charge_amount": q.charge_amount,
        "fx_rate": str(q.fx_rate) if q.fx_rate is not None else None,
    }


@router.post("/deposits", status_code=201)
async def create_deposit(
    body: DepositRequest, user: CurrentUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    try:
        deposit, next_step = await pay.create_deposit(
            session,
            paystack,
            user,
            channel=body.channel,
            usd_cents=body.amount_usd_cents,
            phone=body.phone,
            recipient=body.recipient,
        )
    except pay.PaymentError as exc:
        await session.rollback()
        raise _payment_error(exc) from exc
    return {"deposit": pay.deposit_view(deposit), "next": next_step}


@router.get("/deposits/{reference}")
async def get_deposit(
    reference: str, user: CurrentUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    """Apps poll this after redirect / STK push until status leaves ``pending``."""
    deposit = await session.scalar(
        select(Deposit).where(Deposit.reference == reference, Deposit.payer_id == user.id)
    )
    if deposit is None:
        raise ApiError(404, "not_found", "Deposit not found.")
    if deposit.status == "pending" and deposit.created_at < utcnow() - _POLL_VERIFY_AFTER:
        await pay.refresh_from_paystack(session, paystack, deposit)
        await session.refresh(deposit)
    return pay.deposit_view(deposit)


@router.post("/transfers", status_code=201)
async def transfer(body: TransferRequest, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    try:
        txn = await pay.transfer(
            session,
            user,
            recipient=body.recipient,
            usd_cents=body.amount_usd_cents,
            idempotency_key=body.idempotency_key,
            note=body.note,
        )
    except pay.PaymentError as exc:
        await session.rollback()
        raise _payment_error(exc) from exc
    await session.commit()
    return {"transaction_id": txn.id, "amount_usd_cents": body.amount_usd_cents}
