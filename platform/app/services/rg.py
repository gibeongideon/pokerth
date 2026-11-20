"""Responsible gaming (Phase 5.8): player limits and self-exclusion.

Windows are rolling: day = last 24 h, week = 7 days, month = 30 days.
Loss = what the player paid into tables minus what came back (refunds and
prizes) in the window, never below zero.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.models import Deposit, JournalTransaction, LedgerAccount, LedgerEntry, RgLimit, User
from app.services import config_registry as cfg
from app.services import ledger

Kind = Literal["deposit", "loss"]
Period = Literal["day", "week", "month"]
WINDOWS: dict[str, timedelta] = {
    "day": timedelta(hours=24),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}
EXCLUSIONS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "6m": timedelta(days=182),
    "permanent": None,
}
_FOREVER = datetime(9999, 12, 31, tzinfo=UTC)


class RgBlockedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_excluded(user: User) -> bool:
    return user.excluded_until is not None and user.excluded_until > utcnow()


def check_not_excluded(user: User) -> None:
    if is_excluded(user):
        raise RgBlockedError(
            "self_excluded", "You have paused real-money play. You can still withdraw."
        )


async def _limits(session: AsyncSession, user_id: uuid.UUID) -> list[RgLimit]:
    rows = list((await session.scalars(select(RgLimit).where(RgLimit.user_id == user_id))).all())
    now = utcnow()
    for row in rows:  # apply looser limits whose cooling-off has passed
        if row.pending_effective_at is not None and row.pending_effective_at <= now:
            row.amount_cents = row.pending_amount_cents
            row.pending_amount_cents, row.pending_effective_at = None, None
    return rows


async def deposited(session: AsyncSession, user_id: uuid.UUID, window: timedelta) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Deposit.credit_usd_cents), 0))
        .where(Deposit.payer_id == user_id, Deposit.status.in_(("pending", "success")))
        .where(Deposit.created_at > utcnow() - window)
    )
    return int(total or 0)


async def lost(session: AsyncSession, user_id: uuid.UUID, window: timedelta) -> int:
    net = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0))
        .join(JournalTransaction, JournalTransaction.id == LedgerEntry.transaction_id)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerAccount.code == ledger.user_available(user_id))
        .where(JournalTransaction.kind.in_(("buy_in", "refund", "prize")))
        .where(JournalTransaction.meta["table_id"].astext.is_not(None))
        .where(JournalTransaction.created_at > utcnow() - window)
    )
    return max(0, -int(net or 0))


async def check_deposit(session: AsyncSession, user: User, usd_cents: int) -> None:
    check_not_excluded(user)
    for row in await _limits(session, user.id):
        if row.kind == "deposit" and row.amount_cents is not None:
            used = await deposited(session, user.id, WINDOWS[row.period])
            if used + usd_cents > row.amount_cents:
                raise RgBlockedError(
                    "deposit_limit",
                    f"This goes over the {row.period}ly deposit limit you set "
                    f"(${row.amount_cents / 100:.2f}).",
                )


async def check_play(session: AsyncSession, user: User, cost_cents: int) -> None:
    check_not_excluded(user)
    for row in await _limits(session, user.id):
        if row.kind == "loss" and row.amount_cents is not None:
            used = await lost(session, user.id, WINDOWS[row.period])
            if used + cost_cents > row.amount_cents:
                raise RgBlockedError(
                    "loss_limit",
                    f"This could go over the {row.period}ly loss limit you set "
                    f"(${row.amount_cents / 100:.2f}).",
                )


async def set_limit(
    session: AsyncSession, user: User, kind: Kind, period: Period, amount_cents: int | None
) -> RgLimit:
    """Tighter applies now; looser or removal waits for the cooling-off. Caller commits."""
    rows = await _limits(session, user.id)
    row = next((r for r in rows if r.kind == kind and r.period == period), None)
    if row is None:
        row = RgLimit(user_id=user.id, kind=kind, period=period, amount_cents=None)
        session.add(row)
    current = row.amount_cents
    tighter = amount_cents is not None and (current is None or amount_cents <= current)
    delay = await cfg.get_int(session, "rg.limit_increase_delay_hours")
    if tighter or delay == 0:
        row.amount_cents = amount_cents
        row.pending_amount_cents, row.pending_effective_at = None, None
    else:
        row.pending_amount_cents = amount_cents
        row.pending_effective_at = utcnow() + timedelta(hours=delay)
    await session.flush()
    return row


async def overview(session: AsyncSession, user: User) -> dict[str, Any]:
    rows = {(r.kind, r.period): r for r in await _limits(session, user.id)}
    limits = []
    for kind in ("deposit", "loss"):
        for period, window in WINDOWS.items():
            r = rows.get((kind, period))
            used = (
                await deposited(session, user.id, window)
                if kind == "deposit"
                else await lost(session, user.id, window)
            )
            limits.append(
                {
                    "kind": kind,
                    "period": period,
                    "amount_cents": r.amount_cents if r else None,
                    "used_cents": used,
                    "pending_amount_cents": r.pending_amount_cents if r else None,
                    "pending_effective_at": r.pending_effective_at.isoformat()
                    if r and r.pending_effective_at
                    else None,
                }
            )
    return {
        "limits": limits,
        "excluded_until": user.excluded_until.isoformat()
        if user.excluded_until and is_excluded(user)
        else None,
        "reality_check_minutes": user.reality_check_minutes,
    }


def self_exclude(user: User, period: str) -> datetime:
    """Extend (never shorten) the exclusion. Caller also pulls the player out
    of open tables and commits."""
    delta = EXCLUSIONS[period]
    until = _FOREVER if delta is None else utcnow() + delta
    if user.excluded_until is None or until > user.excluded_until:
        user.excluded_until = until
    return user.excluded_until
