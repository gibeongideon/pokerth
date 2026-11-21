"""The only code allowed to move money (D-008).

``post`` must run inside the caller's DB transaction; the caller commits.
Accounts are locked in id order (SELECT ... FOR UPDATE) so concurrent posts
can't overdraw an account or deadlock each other.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JournalTransaction, LedgerAccount, LedgerEntry

HOUSE_FEES = "house:fees"
PAYSTACK_CLEARING = "paystack:clearing"  # money held at Paystack; goes negative as users deposit

TAX_EXCISE = "tax:excise"
TAX_WITHHOLDING = "tax:withholding"
PAYOUTS_PENDING = "payouts:pending"  # withdrawals confirmed but not yet paid out
PROMOTIONS = "house:promotions"  # referral bonuses and other marketing spend
DEV_CREDIT = "house:dev_credit"  # local seeding only; never used outside env=local
# Play money (free tables): a separate, closed system. Never convertible to real
# money: no deposit, withdrawal or transfer path touches these accounts.
PLAY_BANK = "house:play_bank"

_SYSTEM_ACCOUNTS = {
    HOUSE_FEES: False,
    PAYSTACK_CLEARING: True,
    TAX_EXCISE: False,
    TAX_WITHHOLDING: False,
    PAYOUTS_PENDING: False,
    PROMOTIONS: True,
    DEV_CREDIT: True,
    PLAY_BANK: True,
}


class LedgerError(Exception):
    pass


class InsufficientFundsError(LedgerError):
    def __init__(self, account_code: str) -> None:
        super().__init__(f"insufficient funds in {account_code}")
        self.account_code = account_code


def user_available(user_id: uuid.UUID) -> str:
    return f"user:{user_id}:available"


def user_play(user_id: uuid.UUID) -> str:
    """Play money wallet."""
    return f"user:{user_id}:play"


def table_play(table_id: uuid.UUID) -> str:
    """Play money pot of a free table."""
    return f"table:{table_id}:play"


def table_escrow(table_id: uuid.UUID) -> str:
    """Buy-ins held for one table until it is settled or cancelled."""
    return f"table:{table_id}:escrow"


@dataclass(frozen=True)
class Leg:
    account: str
    amount: int  # signed minor units; positive credits the account


async def _ensure_account(session: AsyncSession, code: str) -> None:
    if code in _SYSTEM_ACCOUNTS:
        values: dict[str, Any] = {"code": code, "allow_negative": _SYSTEM_ACCOUNTS[code]}
    elif code.startswith("table:"):
        values = {"code": code}
    elif code.startswith("user:"):
        values = {"code": code, "user_id": uuid.UUID(code.split(":")[1])}
    else:
        raise LedgerError(f"unknown account {code}")
    await session.execute(
        insert(LedgerAccount).values(**values).on_conflict_do_nothing(index_elements=["code"])
    )


async def post(
    session: AsyncSession,
    *,
    idempotency_key: str,
    kind: str,
    legs: list[Leg],
    memo: str | None = None,
    meta: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
) -> JournalTransaction:
    """Post a balanced transaction. Re-posting the same key returns the
    original transaction without moving money again."""
    existing = await session.scalar(
        select(JournalTransaction).where(JournalTransaction.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.kind != kind:
            raise LedgerError(f"idempotency key {idempotency_key} reused for {kind}")
        return existing

    if len(legs) < 2:
        raise LedgerError("a transaction needs at least two legs")
    if any(leg.amount == 0 for leg in legs):
        raise LedgerError("zero-amount leg")
    if sum(leg.amount for leg in legs) != 0:
        raise LedgerError("transaction does not balance")

    net: dict[str, int] = defaultdict(int)
    for leg in legs:
        net[leg.account] += leg.amount

    for code in sorted(net):
        await _ensure_account(session, code)
    accounts = (
        (
            await session.execute(
                select(LedgerAccount)
                .where(LedgerAccount.code.in_(net.keys()))
                .order_by(LedgerAccount.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_code = {a.code: a for a in accounts}

    for code, delta in net.items():
        acct = by_code[code]
        if not acct.allow_negative and acct.balance + delta < 0:
            raise InsufficientFundsError(code)

    txn = JournalTransaction(
        idempotency_key=idempotency_key, kind=kind, memo=memo, meta=meta or {}, actor_id=actor_id
    )
    session.add(txn)
    await session.flush()
    for leg in legs:
        session.add(
            LedgerEntry(
                transaction_id=txn.id, account_id=by_code[leg.account].id, amount=leg.amount
            )
        )
    for code, delta in net.items():
        by_code[code].balance += delta
    await session.flush()
    return txn


async def balance(session: AsyncSession, code: str) -> int:
    value = await session.scalar(select(LedgerAccount.balance).where(LedgerAccount.code == code))
    return int(value or 0)
