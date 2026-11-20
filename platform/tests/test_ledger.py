import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import LedgerAccount, LedgerEntry
from app.services import ledger
from app.services.ledger import Leg
from tests.conftest import MakeUser


async def _fund(s: AsyncSession, user_id: uuid.UUID, cents: int, key: str) -> None:
    await ledger.post(
        s,
        idempotency_key=key,
        kind="deposit",
        legs=[Leg(ledger.user_available(user_id), cents), Leg(ledger.PAYSTACK_CLEARING, -cents)],
    )


async def test_post_balanced_and_idempotent(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    user, _ = await make_user()
    async with sessions() as s:
        await _fund(s, user.id, 500, "k1")
        await s.commit()
    async with sessions() as s:
        await _fund(s, user.id, 500, "k1")  # same key: no second credit
        await s.commit()
        assert await ledger.balance(s, ledger.user_available(user.id)) == 500
        assert await ledger.balance(s, ledger.PAYSTACK_CLEARING) == -500


async def test_rejects_unbalanced_and_zero_legs(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    user, _ = await make_user()
    acct = ledger.user_available(user.id)
    async with sessions() as s:
        with pytest.raises(ledger.LedgerError):
            await ledger.post(
                s,
                idempotency_key="u1",
                kind="adjustment",
                legs=[Leg(acct, 100), Leg(ledger.PAYSTACK_CLEARING, -99)],
            )
        with pytest.raises(ledger.LedgerError):
            await ledger.post(
                s,
                idempotency_key="u2",
                kind="adjustment",
                legs=[Leg(acct, 0), Leg(ledger.PAYSTACK_CLEARING, 0)],
            )


async def test_insufficient_funds(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    a, _ = await make_user()
    b, _ = await make_user()
    async with sessions() as s:
        await _fund(s, a.id, 100, "f")
        await s.commit()
    async with sessions() as s:
        with pytest.raises(ledger.InsufficientFundsError):
            await ledger.post(
                s,
                idempotency_key="t",
                kind="p2p_transfer",
                legs=[
                    Leg(ledger.user_available(a.id), -101),
                    Leg(ledger.user_available(b.id), 101),
                ],
            )


async def test_concurrent_debits_never_overdraw(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    payer, _ = await make_user()
    payee, _ = await make_user()
    async with sessions() as s:
        await _fund(s, payer.id, 1000, "seed")
        await s.commit()

    async def spend(i: int) -> bool:
        async with sessions() as s:
            try:
                await ledger.post(
                    s,
                    idempotency_key=f"spend-{i}",
                    kind="p2p_transfer",
                    legs=[
                        Leg(ledger.user_available(payer.id), -300),
                        Leg(ledger.user_available(payee.id), 300),
                    ],
                )
                await s.commit()
                return True
            except ledger.InsufficientFundsError:
                await s.rollback()
                return False

    results = await asyncio.gather(*(spend(i) for i in range(10)))
    assert sum(results) == 3  # 3 x 300 fits in 1000, the 4th does not

    async with sessions() as s:
        assert await ledger.balance(s, ledger.user_available(payer.id)) == 100
        # Every balance equals the sum of its entries, and the books sum to zero.
        total = await s.scalar(select(func.sum(LedgerEntry.amount)))
        assert total == 0
        for acct in (await s.execute(select(LedgerAccount))).scalars():
            entries = await s.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.account_id == acct.id
                )
            )
            assert entries == acct.balance
