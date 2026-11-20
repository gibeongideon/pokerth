"""Deposits (card + M-Pesa), fund-a-friend and wallet-to-wallet transfers.

A deposit is only credited by ``settle_deposit``, which requires Paystack's
status to be ``success`` AND the amount and currency to equal what we asked
for (D-006). Settlement is idempotent: the deposit row is locked and the
ledger post uses ``deposit:<reference>`` as its idempotency key.
"""

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Deposit, JournalTransaction, LedgerAccount, LedgerEntry, User
from app.services import config_registry as cfg
from app.services import ledger, rg
from app.services.paystack import PaystackClient, PaystackError

log = logging.getLogger(__name__)

Channel = Literal["card", "mpesa"]
DEPOSIT_PREFIX = "DEP-"
_FAILED_STATES = {"failed", "abandoned", "reversed"}


class PaymentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ------------------------------------------------------------------ helpers

_KE_PHONE = re.compile(r"^(?:\+?254|0)([17]\d{8})$")


def normalize_ke_phone(raw: str) -> str:
    """07XXXXXXXX / 01XXXXXXXX / 2547... / +2547... -> +2547XXXXXXXX."""
    m = _KE_PHONE.match(re.sub(r"[\s-]", "", raw))
    if not m:
        raise PaymentError("invalid_phone", "Enter a Kenyan mobile number, e.g. 0712 345 678.")
    return f"+254{m.group(1)}"


def kes_reference(usd_cents: int, rate: Decimal) -> int:
    """Whole KES shown next to a USD amount, for reference only."""
    return int((Decimal(usd_cents) * rate / 100).to_integral_value(rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Quote:
    channel: Channel
    credit_usd_cents: int
    charge_currency: str
    charge_amount: int  # Paystack subunits
    fx_rate: Decimal | None  # KES per USD actually applied (incl. spread)


async def quote(session: AsyncSession, channel: Channel, usd_cents: int) -> Quote:
    """What the user will be charged for ``usd_cents`` of wallet credit."""
    lo = await cfg.get_int(session, "deposit.min_usd_cents")
    hi = await cfg.get_int(session, "deposit.max_usd_cents")
    if not lo <= usd_cents <= hi:
        raise PaymentError(
            "amount_out_of_range", f"Deposit must be between ${lo / 100:.2f} and ${hi / 100:.2f}."
        )
    if channel == "card":
        return Quote("card", usd_cents, "USD", usd_cents, None)

    rate = await cfg.get_decimal(session, "fx.usd_kes_rate")
    spread = await cfg.get_decimal(session, "fx.spread_pct")
    applied = rate * (1 + spread / 100)
    # M-Pesa takes whole shillings; round up so the credit is always covered.
    kes_whole = (Decimal(usd_cents) * applied / 100).to_integral_value(rounding=ROUND_CEILING)
    return Quote("mpesa", usd_cents, "KES", int(kes_whole) * 100, applied)


async def _require_real_money(session: AsyncSession) -> None:
    if not await cfg.get_bool(session, "real_money_enabled"):
        raise PaymentError("real_money_disabled", "Real-money play is not available yet.", 403)


async def _require_tier(session: AsyncSession, user: User, setting: str) -> None:
    needed = await cfg.get_int(session, setting)
    if user.kyc_tier < needed:
        raise PaymentError(
            "kyc_required", f"Verify your identity (level {needed}) to continue.", 403
        )


def _require_terms(user: User) -> None:
    if user.terms_accepted_at is None:
        raise PaymentError("terms_required", "Accept the terms and confirm you are 18+.", 403)


async def find_recipient(session: AsyncSession, handle: str) -> User:
    handle = handle.strip().lower()
    column = User.email if "@" in handle else User.username
    user = await session.scalar(select(User).where(column == handle))
    if user is None or user.status != "active":
        raise PaymentError(
            "recipient_not_found", "No active player with that username or email.", 404
        )
    return user


# ----------------------------------------------------------------- deposits


async def create_deposit(
    session: AsyncSession,
    paystack: PaystackClient,
    payer: User,
    *,
    channel: Channel,
    usd_cents: int,
    phone: str | None = None,
    recipient: str | None = None,
) -> tuple[Deposit, dict[str, Any]]:
    """Validate, record a pending deposit, then start the Paystack charge.

    Returns the deposit and what the app needs next: ``authorization_url`` /
    ``access_code`` for card, or the STK-push status for M-Pesa.
    """
    await _require_real_money(session)
    _require_terms(payer)
    try:
        await rg.check_deposit(session, payer, usd_cents)
    except rg.RgBlockedError as exc:
        raise PaymentError(exc.code, str(exc), 403) from exc
    await _require_tier(session, payer, "kyc.deposit_min_tier")
    if not paystack.enabled:
        raise PaymentError("payments_unavailable", "Payments are not configured.", 503)

    beneficiary = payer
    if recipient:
        if not await cfg.get_bool(session, "deposit_on_behalf_enabled"):
            raise PaymentError("feature_disabled", "Funding another player is turned off.", 403)
        beneficiary = await find_recipient(session, recipient)

    q = await quote(session, channel, usd_cents)

    daily_max = await cfg.get_int(session, "deposit.daily_max_usd_cents")
    last_24h = await session.scalar(
        select(func.coalesce(func.sum(Deposit.credit_usd_cents), 0))
        .where(Deposit.payer_id == payer.id)
        .where(Deposit.status.in_(("pending", "success")))
        .where(Deposit.created_at > utcnow() - timedelta(hours=24))
    )
    if int(last_24h or 0) + usd_cents > daily_max:
        raise PaymentError("daily_limit", "This would go over your daily deposit limit.")

    msisdn = None
    if channel == "mpesa":
        msisdn = normalize_ke_phone(phone or payer.phone or "")

    deposit = Deposit(
        reference=f"{DEPOSIT_PREFIX}{secrets.token_hex(10).upper()}",
        payer_id=payer.id,
        beneficiary_id=beneficiary.id,
        channel=channel,
        status="pending",
        credit_usd_cents=q.credit_usd_cents,
        charge_currency=q.charge_currency,
        charge_amount=q.charge_amount,
        fx_rate=q.fx_rate,
        phone=msisdn,
    )
    session.add(deposit)
    await session.commit()  # the row must exist before Paystack can call back

    metadata = {"deposit_id": str(deposit.id), "beneficiary_id": str(beneficiary.id)}
    try:
        if channel == "card":
            data = await paystack.initialize_transaction(
                email=payer.email,
                amount=q.charge_amount,
                currency=q.charge_currency,
                reference=deposit.reference,
                callback_url=f"{get_settings().public_base_url}/wallet/deposit/return",
                channels=["card"],
                metadata=metadata,
            )
            next_step = {
                "type": "redirect",
                "authorization_url": data.get("authorization_url"),
                "access_code": data.get("access_code"),
            }
        else:
            assert msisdn is not None
            data = await paystack.charge_mpesa(
                email=payer.email,
                amount=q.charge_amount,
                phone=msisdn,
                reference=deposit.reference,
                metadata=metadata,
            )
            next_step = {
                "type": "mpesa_prompt",
                "status": data.get("status"),
                "display_text": data.get("display_text")
                or "Check your phone and enter your M-Pesa PIN.",
            }
    except PaystackError as exc:
        deposit.status = "failed"
        deposit.gateway_response = str(exc)[:500]
        await session.commit()
        log.warning("paystack start failed for %s: %s", deposit.reference, exc)
        raise PaymentError(
            "payment_start_failed", "Could not start the payment. Try again.", 502
        ) from exc

    return deposit, next_step


async def settle_deposit(session: AsyncSession, reference: str, tx: dict[str, Any]) -> bool:
    """Apply a Paystack transaction result to a deposit. Returns True if this
    call credited the wallet. Caller commits."""
    deposit = await session.scalar(
        select(Deposit).where(Deposit.reference == reference).with_for_update()
    )
    if deposit is None:
        log.warning("paystack result for unknown reference %s", reference)
        return False
    if deposit.status == "success":
        return False

    status = str(tx.get("status") or "")
    deposit.gateway_response = str(tx.get("gateway_response") or status)[:500]
    if tx.get("id") is not None:
        deposit.paystack_id = str(tx["id"])

    if status != "success":
        if status in _FAILED_STATES and deposit.status == "pending":
            deposit.status = "failed" if status != "abandoned" else "abandoned"
        return False

    amount = tx.get("amount")
    currency = str(tx.get("currency") or "").upper()
    if amount != deposit.charge_amount or currency != deposit.charge_currency:
        deposit.status = "mismatch"
        log.error(
            "deposit %s mismatch: expected %s %s, got %s %s",
            reference,
            deposit.charge_amount,
            deposit.charge_currency,
            amount,
            currency,
        )
        return False

    txn = await ledger.post(
        session,
        idempotency_key=f"deposit:{reference}",
        kind="deposit",
        legs=[
            ledger.Leg(ledger.user_available(deposit.beneficiary_id), deposit.credit_usd_cents),
            ledger.Leg(ledger.PAYSTACK_CLEARING, -deposit.credit_usd_cents),
        ],
        memo=f"{deposit.channel} deposit",
        meta={"reference": reference, "payer_id": str(deposit.payer_id)},
        actor_id=deposit.payer_id,
    )
    deposit.status = "success"
    deposit.journal_id = txn.id
    deposit.paid_at = utcnow()
    return True


async def refresh_from_paystack(
    session: AsyncSession, paystack: PaystackClient, deposit: Deposit
) -> None:
    """Ask Paystack for the latest state of a pending deposit and settle it."""
    if deposit.status != "pending" or not paystack.enabled:
        return
    try:
        tx = await paystack.verify_transaction(deposit.reference)
    except PaystackError as exc:
        log.info("verify %s: %s", deposit.reference, exc)
        return
    await settle_deposit(session, deposit.reference, tx)
    await session.commit()


# ---------------------------------------------------------------- transfers


async def transfer(
    session: AsyncSession,
    sender: User,
    *,
    recipient: str,
    usd_cents: int,
    idempotency_key: str,
    note: str | None = None,
) -> JournalTransaction:
    """Move money from one wallet to another. Caller commits."""
    await _require_real_money(session)
    if not await cfg.get_bool(session, "p2p_transfers_enabled"):
        raise PaymentError("feature_disabled", "Transfers between players are turned off.", 403)
    _require_terms(sender)
    if rg.is_excluded(sender):
        raise PaymentError("self_excluded", "Transfers are paused while you take a break.", 403)
    await _require_tier(session, sender, "kyc.p2p_min_tier")

    to = await find_recipient(session, recipient)
    if to.id == sender.id:
        raise PaymentError("self_transfer", "You can't send money to yourself.")
    max_one = await cfg.get_int(session, "p2p.max_usd_cents")
    if not 0 < usd_cents <= max_one:
        raise PaymentError("amount_out_of_range", f"Transfers are limited to ${max_one / 100:.2f}.")

    key = f"p2p:{sender.id}:{idempotency_key}"
    existing = await session.scalar(
        select(JournalTransaction).where(JournalTransaction.idempotency_key == key)
    )
    if existing is not None:
        return existing

    daily_max = await cfg.get_int(session, "p2p.daily_max_usd_cents")
    sent_24h = await session.scalar(
        select(func.coalesce(func.sum(-LedgerEntry.amount), 0))
        .join(JournalTransaction, JournalTransaction.id == LedgerEntry.transaction_id)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(JournalTransaction.kind == "p2p_transfer")
        .where(LedgerAccount.code == ledger.user_available(sender.id))
        .where(LedgerEntry.amount < 0)
        .where(JournalTransaction.created_at > utcnow() - timedelta(hours=24))
    )
    if int(sent_24h or 0) + usd_cents > daily_max:
        raise PaymentError("daily_limit", "This would go over your daily transfer limit.")

    try:
        return await ledger.post(
            session,
            idempotency_key=key,
            kind="p2p_transfer",
            legs=[
                ledger.Leg(ledger.user_available(sender.id), -usd_cents),
                ledger.Leg(ledger.user_available(to.id), usd_cents),
            ],
            memo=(note or "")[:140] or None,
            meta={"from": str(sender.id), "to": str(to.id)},
            actor_id=sender.id,
        )
    except ledger.InsufficientFundsError as exc:
        raise PaymentError("insufficient_funds", "Not enough money in your wallet.") from exc


def deposit_view(d: Deposit) -> dict[str, Any]:
    return {
        "reference": d.reference,
        "status": d.status,
        "channel": d.channel,
        "credit_usd_cents": d.credit_usd_cents,
        "charge_currency": d.charge_currency,
        "charge_amount": d.charge_amount,
        "fx_rate": str(d.fx_rate) if d.fx_rate is not None else None,
        "beneficiary_id": str(d.beneficiary_id),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "paid_at": d.paid_at.isoformat() if d.paid_at else None,
    }
