"""Withdrawals to M-Pesa (Phase 4). See ``app/models/payouts.py`` for the states.

Ledger:
  confirm:          user:available -amount        payouts:pending +amount
  paid out:         payouts:pending -amount       paystack:clearing +(amount-fee), house:fees +fee
  failed/rejected:  payouts:pending -amount       user:available +amount
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.money import money
from app.core.security import utcnow
from app.models import Deposit, PayoutDestination, User, Withdrawal
from app.services import config_registry as cfg
from app.services import ledger
from app.services.ledger import Leg
from app.services.mailer import Mailer
from app.services.payments import PaymentError, normalize_ke_phone
from app.services.paystack import PaystackClient, PaystackError

log = logging.getLogger(__name__)

# Lowercase: Paystack documents transfer references as lowercase. Older rows
# used "WD-"; lookups match either.
PREFIX = "wd-"
_MAX_CODE_ATTEMPTS = 5
# Unconfirmed withdrawals count too, so a limit can't be beaten by opening
# many small withdrawals and confirming them all.
_COUNTS_TOWARD_LIMITS = (
    "awaiting_confirmation",
    "pending_review",
    "approved",
    "processing",
    "success",
)
_FINAL = ("success", "failed", "reversed", "rejected", "cancelled", "expired")
# Paystack transfer statuses that mean the money did not leave.
_FAILED_STATUSES = ("failed", "reversed", "abandoned", "blocked", "rejected")


def is_withdrawal_reference(reference: str) -> bool:
    return reference.lower().startswith("wd-")


def _err(code: str, message: str, status: int = 400) -> PaymentError:
    return PaymentError(code, message, status)


# -------------------------------------------------------------- destinations


async def add_destination(session: AsyncSession, user: User, phone: str) -> PayoutDestination:
    """Register an M-Pesa number for payouts. It must be the number on the
    player's profile, so winnings only go to the account holder (D-014)."""
    msisdn = normalize_ke_phone(phone)
    if user.phone is None:
        raise _err("phone_required", "Add your M-Pesa number to your profile first.", 403)
    if msisdn != user.phone:
        raise _err("not_your_phone", "Payouts can only go to the number on your profile.", 403)
    existing = await session.scalar(
        select(PayoutDestination).where(
            PayoutDestination.user_id == user.id,
            PayoutDestination.phone == msisdn,
            PayoutDestination.is_active,
        )
    )
    if existing is not None:
        return existing
    dest = PayoutDestination(
        user_id=user.id,
        kind="mpesa",
        phone=msisdn,
        account_name=(user.display_name or user.username or user.email)[:100],
    )
    session.add(dest)
    await session.flush()
    return dest


# ---------------------------------------------------------------- quoting


async def quote(session: AsyncSession, usd_cents: int) -> dict[str, Any]:
    flat = await cfg.get_int(session, "withdraw.fee_flat_usd_cents")
    pct = await cfg.get_decimal(session, "withdraw.fee_pct")
    free_above = await cfg.get_int(session, "withdraw.free_above_usd_cents")
    fee = flat + int((Decimal(usd_cents) * pct / 100).quantize(Decimal(1), ROUND_HALF_UP))
    if free_above and usd_cents >= free_above:
        fee = 0
    if fee >= usd_cents:
        raise _err("amount_too_small", "The amount does not cover the withdrawal fee.")
    rate = await cfg.get_decimal(session, "fx.usd_kes_rate")
    spread = await cfg.get_decimal(session, "fx.spread_pct")
    applied = rate * (1 - spread / 100)
    kes_whole = (Decimal(usd_cents - fee) * applied / 100).to_integral_value(rounding=ROUND_FLOOR)
    return {
        "amount_usd_cents": usd_cents,
        "fee_usd_cents": fee,
        "payout_currency": "KES",
        "payout_amount": int(kes_whole) * 100,
        "fx_rate": applied,
    }


# --------------------------------------------------------------- requesting


async def _withdrawn_since(
    session: AsyncSession,
    user_id: uuid.UUID,
    hours: int,
    *,
    exclude: uuid.UUID | None = None,
    statuses: tuple[str, ...] = _COUNTS_TOWARD_LIMITS,
) -> int:
    q = (
        select(func.coalesce(func.sum(Withdrawal.amount_usd_cents), 0))
        .where(Withdrawal.user_id == user_id)
        .where(Withdrawal.status.in_(statuses))
        .where(Withdrawal.created_at > utcnow() - timedelta(hours=hours))
    )
    if exclude is not None:
        q = q.where(Withdrawal.id != exclude)
    return int(await session.scalar(q) or 0)


async def _lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialize one player's withdrawals, so limit checks can't be raced."""
    await session.execute(
        select(User.id)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _check_phone_hold(session: AsyncSession, user: User) -> None:
    hold = await cfg.get_int(session, "withdraw.phone_change_hold_hours")
    if hold and user.phone_changed_at and user.phone_changed_at > utcnow() - timedelta(hours=hold):
        raise _err(
            "phone_recently_changed",
            f"Your M-Pesa number changed recently. Withdrawals open {hold}h after the change.",
            403,
        )


async def _check_limits(
    session: AsyncSession, user: User, usd_cents: int, *, exclude: uuid.UUID | None = None
) -> None:
    """Amount range, KYC tier and daily/monthly limits. Caller holds the user lock."""
    lo = await cfg.get_int(session, "withdraw.min_usd_cents")
    hi = await cfg.get_int(session, "withdraw.max_usd_cents")
    if not lo <= usd_cents <= hi:
        raise _err("amount_out_of_range", f"Withdraw between {money(lo)} and {money(hi)}.")
    day = await _withdrawn_since(session, user.id, 24, exclude=exclude)
    tier = await cfg.get_int(session, "kyc.withdraw_min_tier")
    # Level 2 is judged on the 24h total, so splitting a big withdrawal doesn't avoid it.
    if day + usd_cents > await cfg.get_int(session, "kyc.withdraw_tier2_above_usd_cents"):
        tier = max(tier, 2)
    if user.kyc_tier < tier:
        raise _err("kyc_required", f"Verify your identity (level {tier}) to withdraw this.", 403)
    for hours, key, total in (
        (24, "withdraw.daily_max_usd_cents", day),
        (720, "withdraw.monthly_max_usd_cents", None),
    ):
        used = (
            total
            if total is not None
            else await _withdrawn_since(session, user.id, hours, exclude=exclude)
        )
        if used + usd_cents > await cfg.get_int(session, key):
            period = "daily" if hours == 24 else "monthly"
            raise _err(f"{period}_limit", f"This would go over your {period} withdrawal limit.")


def _code_hash(withdrawal_id: uuid.UUID, code: str) -> str:
    key = get_settings().jwt_secret.get_secret_value().encode()
    return hmac.new(key, f"{withdrawal_id}:{code}".encode(), hashlib.sha256).hexdigest()


async def request(
    session: AsyncSession,
    mailer: Mailer,
    user: User,
    *,
    destination_id: uuid.UUID,
    usd_cents: int,
) -> Withdrawal:
    """Check every rule and create the withdrawal. If email codes are on, the
    money only moves when the player confirms with the code."""
    if not await cfg.get_bool(session, "real_money_enabled") or not await cfg.get_bool(
        session, "withdrawals_enabled"
    ):
        raise _err("withdrawals_disabled", "Withdrawals are not available right now.", 403)
    if user.terms_accepted_at is None:
        raise _err("terms_required", "Accept the terms and confirm you are 18+.", 403)
    await _lock_user(session, user.id)
    await _check_phone_hold(session, user)
    open_unconfirmed = await session.scalar(
        select(func.count())
        .select_from(Withdrawal)
        .where(Withdrawal.user_id == user.id, Withdrawal.status == "awaiting_confirmation")
        .where(Withdrawal.otp_expires_at > utcnow())
    )
    if (open_unconfirmed or 0) >= await cfg.get_int(session, "withdraw.max_open_unconfirmed"):
        raise _err("too_many_open", "Confirm or cancel your other withdrawals first.", 409)
    await _check_limits(session, user, usd_cents)
    if await ledger.balance(session, ledger.user_available(user.id)) < usd_cents:
        raise _err("insufficient_funds", "Not enough money in your wallet.")

    dest = await session.get(PayoutDestination, destination_id)
    if dest is None or dest.user_id != user.id or not dest.is_active:
        raise _err("destination_not_found", "Payout number not found.", 404)

    q = await quote(session, usd_cents)
    w = Withdrawal(
        reference=f"{PREFIX}{secrets.token_hex(10)}",
        user_id=user.id,
        destination_id=dest.id,
        status="awaiting_confirmation",
        amount_usd_cents=usd_cents,
        fee_usd_cents=q["fee_usd_cents"],
        payout_currency="KES",
        payout_amount=q["payout_amount"],
        fx_rate=q["fx_rate"],
    )
    session.add(w)
    await session.flush()

    if not await cfg.get_bool(session, "withdraw.require_email_code"):
        await _confirmed(session, w, user)
        return w

    code = f"{secrets.randbelow(10**6):06d}"
    ttl = await cfg.get_int(session, "withdraw.code_ttl_seconds")
    w.otp_hash = _code_hash(w.id, code)
    w.otp_expires_at = utcnow() + timedelta(seconds=ttl)
    await session.commit()
    await mailer.send(
        user.email,
        f"Your withdrawal code: {code}",
        f"Use this code to confirm your withdrawal of {money(usd_cents)} "
        f"(KES {q['payout_amount'] // 100:,} to M-Pesa {dest.phone[-4:].rjust(10, '*')}).\n\n"
        f"    {code}\n\nIt expires in {ttl // 60} minutes. If this wasn't you, "
        "don't share the code and sign out of all devices.",
    )
    return w


async def confirm(session: AsyncSession, user: User, reference: str, code: str) -> Withdrawal:
    """Check the emailed code and take the money out of the wallet."""
    w = await _lock(session, reference, user.id)
    if w.status != "awaiting_confirmation":
        raise _err("not_awaiting_code", "This withdrawal is not waiting for a code.", 409)
    if w.otp_expires_at is None or w.otp_expires_at <= utcnow():
        w.status = "expired"
        raise _err("code_expired", "The code has expired. Start the withdrawal again.", 410)
    w.otp_attempts += 1
    if not hmac.compare_digest(_code_hash(w.id, code.strip()), w.otp_hash or ""):
        if w.otp_attempts >= _MAX_CODE_ATTEMPTS:
            w.status = "expired"
            raise _err("too_many_attempts", "Too many wrong codes. Start again.", 429)
        raise _err("wrong_code", "That code is not right.", 400)
    # Limits again, now under the player's lock: other withdrawals may have
    # been confirmed since this one was requested.
    await _lock_user(session, user.id)
    await _check_phone_hold(session, user)
    await _check_limits(session, user, w.amount_usd_cents, exclude=w.id)
    await _confirmed(session, w, user)
    return w


async def _confirmed(session: AsyncSession, w: Withdrawal, user: User) -> None:
    try:
        await ledger.post(
            session,
            idempotency_key=f"withdraw:{w.reference}",
            kind="withdrawal",
            legs=[
                Leg(ledger.user_available(w.user_id), -w.amount_usd_cents),
                Leg(ledger.PAYOUTS_PENDING, w.amount_usd_cents),
            ],
            memo="withdrawal to M-Pesa",
            meta={"reference": w.reference},
            actor_id=w.user_id,
        )
    except ledger.InsufficientFundsError as exc:
        raise _err("insufficient_funds", "Not enough money in your wallet.") from exc

    reasons = []
    # Judged on the 24h total of confirmed withdrawals, so many small ones
    # can't slip past review.
    confirmed_day = await _withdrawn_since(
        session,
        w.user_id,
        24,
        exclude=w.id,
        statuses=("pending_review", "approved", "processing", "success"),
    )
    if confirmed_day + w.amount_usd_cents > await cfg.get_int(
        session, "withdraw.auto_approve_max_usd_cents"
    ):
        reasons.append("24h total above auto-approve limit")
    hours = await cfg.get_int(session, "withdraw.deposit_review_hours")
    recent = await session.scalar(
        select(Deposit.id)
        .where(Deposit.beneficiary_id == w.user_id, Deposit.status == "success")
        .where(Deposit.paid_at > utcnow() - timedelta(hours=hours))
        .limit(1)
    )
    if hours and recent is not None:
        reasons.append(f"deposit in the last {hours}h")
    w.status = "pending_review" if reasons else "approved"
    w.review_reasons = "; ".join(reasons) or None
    w.confirmed_at = utcnow()
    w.otp_hash = None


async def _lock(session: AsyncSession, reference: str, user_id: uuid.UUID | None) -> Withdrawal:
    # populate_existing: the session may already hold this row from before the
    # lock (expire_on_commit=False); without it we'd act on stale values.
    q = (
        select(Withdrawal)
        .where(Withdrawal.reference == reference)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user_id is not None:
        q = q.where(Withdrawal.user_id == user_id)
    w = await session.scalar(q)
    if w is None:
        raise _err("not_found", "Withdrawal not found.", 404)
    return w


# ----------------------------------------------------------- cancel/review


async def _refund(session: AsyncSession, w: Withdrawal, why: str) -> None:
    await ledger.post(
        session,
        idempotency_key=f"withdraw-refund:{w.reference}",
        kind="refund",
        legs=[
            Leg(ledger.PAYOUTS_PENDING, -w.amount_usd_cents),
            Leg(ledger.user_available(w.user_id), w.amount_usd_cents),
        ],
        memo=f"withdrawal returned ({why})",
        meta={"reference": w.reference},
    )


async def cancel(session: AsyncSession, user: User, reference: str) -> Withdrawal:
    w = await _lock(session, reference, user.id)
    if w.status == "awaiting_confirmation":
        w.status = "cancelled"
    elif w.status == "pending_review":
        await _refund(session, w, "cancelled")
        w.status = "cancelled"
    else:
        raise _err("cannot_cancel", "This withdrawal can no longer be cancelled.", 409)
    return w


async def review(
    session: AsyncSession, admin: User, reference: str, *, approve: bool, note: str | None
) -> Withdrawal:
    w = await _lock(session, reference, None)
    if w.status != "pending_review":
        raise _err("not_in_review", "This withdrawal is not waiting for review.", 409)
    if w.user_id == admin.id:
        raise _err("own_withdrawal", "Another admin must review your own withdrawal.", 403)
    w.reviewed_by, w.reviewed_at, w.review_note = admin.id, utcnow(), note
    if approve:
        w.status = "approved"
    else:
        await _refund(session, w, "rejected")
        w.status = "rejected"
    return w


# ------------------------------------------------------------------ sending


async def send(session: AsyncSession, paystack: PaystackClient, reference: str) -> Withdrawal:
    """Start the Paystack transfer for an approved withdrawal. Safe to call
    again: a retry first asks Paystack whether the transfer already exists."""
    w = await _lock(session, reference, None)
    if w.status != "approved":
        return w
    # Kill switches also stop payouts already in flight (they stay approved).
    if not await cfg.get_bool(session, "real_money_enabled") or not await cfg.get_bool(
        session, "withdrawals_enabled"
    ):
        return w
    if w.send_attempts > 0:
        try:
            existing: dict[str, Any] | None = await paystack.verify_transfer(w.reference)
        except PaystackError as exc:
            if exc.status_code != 404:
                # Can't tell whether the transfer exists: never risk paying twice.
                w.failure_reason = f"verify before resend failed: {exc}"[:500]
                return w
            existing = None
        if existing is not None:
            w.transfer_code = existing.get("transfer_code")
            w.status = "processing"
            await apply_result(session, w.reference, existing, locked=w)
            return w

    w.send_attempts += 1
    dest = await session.get(PayoutDestination, w.destination_id)
    assert dest is not None
    try:
        if dest.recipient_code is None:
            dest.recipient_code = await paystack.create_mpesa_recipient(
                name=dest.account_name, phone="0" + dest.phone[4:]
            )
        data = await paystack.initiate_transfer(
            amount=w.payout_amount,
            recipient=dest.recipient_code,
            reference=w.reference,
            reason="Winnings withdrawal",
        )
    except PaystackError as exc:
        w.failure_reason = f"send attempt {w.send_attempts}: {exc}"[:500]
        log.warning("withdrawal %s send failed: %s", w.reference, exc)
        return w  # stays approved; the worker retries

    w.transfer_code = data.get("transfer_code")
    w.sent_at = utcnow()
    if data.get("status") == "otp":
        # Paystack wants an OTP for transfers: an account setting, not the player's fault.
        w.failure_reason = "Paystack transfer OTP is enabled; disable it for API transfers."
        log.error("withdrawal %s: %s", w.reference, w.failure_reason)
        w.status = "approved"
        return w
    w.status = "processing"
    if data.get("status") in ("success", "failed", "reversed"):
        await apply_result(session, w.reference, data, locked=w)
    return w


async def apply_result(
    session: AsyncSession,
    reference: str,
    data: dict[str, Any],
    locked: Withdrawal | None = None,
) -> bool:
    """Apply a transfer outcome (webhook or verify). Returns True if it changed
    anything. Final states are never changed again."""
    w = locked or await _lock(session, reference, None)
    status = str(data.get("status") or "")
    if w.status == "success" and status == "reversed":
        # Paystack took a completed payout back: the player gets the money back.
        log.error("withdrawal %s reversed after success - refunding the player", reference)
        await ledger.post(
            session,
            idempotency_key=f"withdraw-reversal:{reference}",
            kind="refund",
            legs=[
                Leg(ledger.PAYSTACK_CLEARING, -(w.amount_usd_cents - w.fee_usd_cents)),
                *([Leg(ledger.HOUSE_FEES, -w.fee_usd_cents)] if w.fee_usd_cents else []),
                Leg(ledger.user_available(w.user_id), w.amount_usd_cents),
            ],
            memo="withdrawal reversed by the bank - returned",
            meta={"reference": reference},
        )
        w.status, w.completed_at = "reversed", utcnow()
        w.failure_reason = "reversed after payout"
        return True
    if w.status in _FINAL:
        return False
    if status == "success":
        if data.get("amount") not in (None, w.payout_amount):
            log.error(
                "withdrawal %s paid %s, expected %s", reference, data.get("amount"), w.payout_amount
            )
        legs = [
            Leg(ledger.PAYOUTS_PENDING, -w.amount_usd_cents),
            Leg(ledger.PAYSTACK_CLEARING, w.amount_usd_cents - w.fee_usd_cents),
        ]
        if w.fee_usd_cents:
            legs.append(Leg(ledger.HOUSE_FEES, w.fee_usd_cents))
        await ledger.post(
            session,
            idempotency_key=f"withdraw-done:{reference}",
            kind="withdrawal",
            legs=legs,
            memo="paid to M-Pesa",
            meta={"reference": reference, "transfer_code": data.get("transfer_code")},
        )
        w.status, w.completed_at = "success", utcnow()
        return True
    if status in _FAILED_STATUSES:
        await _refund(session, w, status)
        w.status, w.completed_at = ("reversed" if status == "reversed" else "failed"), utcnow()
        w.failure_reason = str(data.get("reason") or data.get("gateway_response") or status)[:500]
        return True
    return False  # pending / processing: nothing to do yet


async def resolve_stuck(
    session: AsyncSession, paystack: PaystackClient, admin: User, reference: str, note: str
) -> Withdrawal:
    """Admin: settle a withdrawal stuck in approved/processing. Asks Paystack
    first - a paid transfer is booked as paid, anything else is refunded."""
    w = await _lock(session, reference, None)
    if w.status not in ("approved", "processing"):
        raise _err("not_stuck", "Only approved or processing withdrawals can be resolved.", 409)
    if w.user_id == admin.id:
        raise _err("own_withdrawal", "Another admin must resolve your own withdrawal.", 403)
    try:
        data: dict[str, Any] = await paystack.verify_transfer(w.reference)
    except PaystackError as exc:
        if exc.status_code != 404:
            raise _err("paystack_unavailable", f"Couldn't check with Paystack: {exc}", 503) from exc
        data = {"status": "failed", "reason": "transfer never created"}
    if str(data.get("status")) not in ("success", *_FAILED_STATUSES):
        if w.status == "processing":
            raise _err(
                "still_pending", f"Paystack still reports '{data.get('status')}'. Try later.", 409
            )
        data = {"status": "failed", "reason": "never sent"}
    w.reviewed_by, w.reviewed_at, w.review_note = admin.id, utcnow(), note[:500]
    await apply_result(session, w.reference, data, locked=w)
    return w


def view(w: Withdrawal) -> dict[str, Any]:
    return {
        "reference": w.reference,
        "status": w.status,
        "amount_usd_cents": w.amount_usd_cents,
        "fee_usd_cents": w.fee_usd_cents,
        "payout_currency": w.payout_currency,
        "payout_amount": w.payout_amount,
        "fx_rate": str(w.fx_rate),
        "review_reasons": w.review_reasons,
        "failure_reason": w.failure_reason if w.status in ("failed", "reversed") else None,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "completed_at": w.completed_at.isoformat() if w.completed_at else None,
    }
