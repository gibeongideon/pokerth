"""Demo money for free tables.

Every player gets demo dollars (``play.start_usd_cents``). A seat at a free
table costs ``play.table_entry_usd_cents``; winners share the pot like a real
Sit & Go. When a player runs out they can refill (``play.refills_per_day``).

Demo money lives in its own accounts (``user:<id>:play``, ``table:<id>:play``,
``house:play_bank``). No deposit, withdrawal, transfer or real-money table
ever touches them, so it can never turn into real money.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.models import JournalTransaction, LedgerAccount, LedgerEntry, User
from app.services import config_registry as cfg
from app.services import ledger
from app.services.ledger import Leg

KIND_GRANT = "play_grant"
KIND_REFILL = "play_refill"


class PlayError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


async def ensure_started(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Give a player their starting demo money, once."""
    amount = await cfg.get_int(session, "play.start_usd_cents")
    if amount > 0:
        await ledger.post(
            session,
            idempotency_key=f"play-start:{user_id}",
            kind=KIND_GRANT,
            legs=[Leg(ledger.user_play(user_id), amount), Leg(ledger.PLAY_BANK, -amount)],
            memo="demo money to start",
        )


async def balance(session: AsyncSession, user_id: uuid.UUID) -> int:
    await ensure_started(session, user_id)
    return await ledger.balance(session, ledger.user_play(user_id))


async def _refills_since(session: AsyncSession, user_id: uuid.UUID, since: Any) -> list[Any]:
    rows = await session.scalars(
        select(JournalTransaction.created_at)
        .join(LedgerEntry, LedgerEntry.transaction_id == JournalTransaction.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(JournalTransaction.kind == KIND_REFILL)
        .where(LedgerAccount.code == ledger.user_play(user_id))
        .where(JournalTransaction.created_at > since)
        .order_by(JournalTransaction.created_at)
    )
    return list(rows.all())


async def status(session: AsyncSession, user: User) -> dict[str, Any]:
    bal = await balance(session, user.id)
    entry = await cfg.get_int(session, "play.table_entry_usd_cents")
    per_day = await cfg.get_int(session, "play.refills_per_day")
    recent = await _refills_since(session, user.id, utcnow() - timedelta(hours=24))
    next_at = recent[0] + timedelta(hours=24) if per_day and len(recent) >= per_day else None
    return {
        "play_usd_cents": bal,
        "table_entry_usd_cents": entry,
        "refill_to_usd_cents": await cfg.get_int(session, "play.refill_to_usd_cents"),
        "can_refill": bal < max(entry, 1) and per_day > 0 and next_at is None,
        "next_refill_at": next_at.isoformat() if next_at else None,
    }


async def refill(session: AsyncSession, user: User) -> int:
    """Top demo money back up - only when it has run out, limited per day."""
    # One refill at a time per player.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    bal = await balance(session, user.id)
    entry = await cfg.get_int(session, "play.table_entry_usd_cents")
    if bal >= max(entry, 1):
        raise PlayError("not_empty", "You still have demo money to play with.", 409)
    per_day = await cfg.get_int(session, "play.refills_per_day")
    recent = await _refills_since(session, user.id, utcnow() - timedelta(hours=24))
    if per_day <= 0 or len(recent) >= per_day:
        raise PlayError("refill_limit", "You've used today's refill. Come back tomorrow.", 429)
    top_up = await cfg.get_int(session, "play.refill_to_usd_cents") - bal
    if top_up > 0:
        await ledger.post(
            session,
            idempotency_key=f"play-refill:{user.id}:{len(recent)}:{utcnow():%Y%m%d%H%M%S%f}",
            kind=KIND_REFILL,
            legs=[Leg(ledger.user_play(user.id), top_up), Leg(ledger.PLAY_BANK, -top_up)],
            memo="demo money refill",
        )
    return bal + max(top_up, 0)


async def total_refills(session: AsyncSession) -> int:
    """For admin reports."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(JournalTransaction)
            .where(JournalTransaction.kind == KIND_REFILL)
        )
        or 0
    )
