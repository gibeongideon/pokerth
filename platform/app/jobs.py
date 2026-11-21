"""Background jobs. Plain async functions so tests can call them directly;
``app/worker.py`` schedules them with Celery beat."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import Deposit, LedgerAccount, LedgerEntry, Withdrawal
from app.services import config_registry as cfg
from app.services import payments as pay
from app.services import payouts
from app.services import tables as table_svc
from app.services.paystack import PaystackClient, PaystackError

log = logging.getLogger(__name__)


async def expire_stale_deposits(
    sessions: async_sessionmaker[AsyncSession], paystack: PaystackClient
) -> dict[str, int]:
    """Close pending deposits older than ``deposit.pending_expiry_minutes``.

    Paystack says success -> credit the wallet. Failed/abandoned -> record that.
    Unknown to Paystack or still in progress -> ``expired``. An expired deposit
    is still credited if a success webhook arrives later (money was received).
    """
    counts = {"settled": 0, "closed": 0, "kept": 0}
    async with sessions() as session:
        minutes = await cfg.get_int(session, "deposit.pending_expiry_minutes")
        refs = (
            (
                await session.execute(
                    select(Deposit.reference)
                    .where(Deposit.status == "pending")
                    .where(Deposit.created_at < utcnow() - timedelta(minutes=minutes))
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )

    for ref in refs:
        tx: dict[str, Any] | None
        try:
            tx = await paystack.verify_transaction(ref)
        except PaystackError as exc:
            if exc.status_code not in (400, 404):
                counts["kept"] += 1  # Paystack unreachable; retry next run
                continue
            tx = None  # Paystack has never seen this reference
        async with sessions() as session:
            if tx is not None and await pay.settle_deposit(session, ref, tx):
                counts["settled"] += 1
            else:
                deposit = await session.scalar(
                    select(Deposit).where(Deposit.reference == ref).with_for_update()
                )
                if deposit is not None and deposit.status == "pending":
                    deposit.status = "expired"
                counts["closed"] += 1
            await session.commit()
    log.info("expire_stale_deposits %s", counts)
    return counts


async def reconcile_deposits(
    sessions: async_sessionmaker[AsyncSession], paystack: PaystackClient, day: datetime
) -> dict[str, Any]:
    """Compare one UTC day of successful Paystack charges with our deposits.
    Settles anything we missed (e.g. lost webhooks) and reports mismatches."""
    start = day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    report: dict[str, Any] = {"checked": 0, "settled_late": [], "unknown": [], "problems": []}

    page, pages = 1, 1
    while page <= pages:
        txs, pages = await paystack.list_transactions(
            from_iso=start.isoformat(), to_iso=end.isoformat(), page=page
        )
        for tx in txs:
            ref = str(tx.get("reference") or "")
            if tx.get("status") != "success" or not ref.startswith(pay.DEPOSIT_PREFIX):
                continue
            report["checked"] += 1
            async with sessions() as session:
                deposit = await session.scalar(select(Deposit).where(Deposit.reference == ref))
                if deposit is None:
                    report["unknown"].append(ref)
                    continue
                if deposit.status == "success":
                    continue
                if await pay.settle_deposit(session, ref, tx):
                    report["settled_late"].append(ref)
                else:
                    report["problems"].append({"reference": ref, "status": deposit.status})
                await session.commit()
        page += 1

    if report["unknown"] or report["problems"]:
        log.error("deposit reconciliation needs attention: %s", report)
    else:
        log.info("deposit reconciliation ok: %s", report)
    return report


async def process_withdrawals(
    sessions: async_sessionmaker[AsyncSession], paystack: PaystackClient
) -> dict[str, int]:
    """Expire unconfirmed withdrawals, (re)send approved ones, and ask Paystack
    about transfers that have been processing for a while (lost webhooks)."""
    counts = {"expired": 0, "sent": 0, "resolved": 0}
    now = utcnow()
    async with sessions() as session:
        # One conditional UPDATE: a withdrawal confirmed a moment ago (status
        # no longer awaiting_confirmation) is never overwritten.
        expired = await session.execute(
            update(Withdrawal)
            .where(Withdrawal.status == "awaiting_confirmation", Withdrawal.otp_expires_at < now)
            .values(status="expired")
            .returning(Withdrawal.id)
        )
        counts["expired"] = len(expired.all())
        await session.commit()

        stuck = (
            await session.scalars(
                select(Withdrawal.reference).where(
                    Withdrawal.status == "approved", Withdrawal.send_attempts >= 10
                )
            )
        ).all()
        if stuck:
            log.error(
                "withdrawals stuck after 10 send attempts (resolve in admin): %s", list(stuck)
            )

        approved = (
            await session.scalars(
                select(Withdrawal.reference)
                .where(Withdrawal.status == "approved", Withdrawal.send_attempts < 10)
                .limit(100)
            )
        ).all()
        processing = (
            await session.scalars(
                select(Withdrawal.reference)
                .where(Withdrawal.status == "processing")
                .where(Withdrawal.sent_at < now - timedelta(minutes=10))
                .limit(100)
            )
        ).all()

    for ref in approved:
        async with sessions() as session:
            w = await payouts.send(session, paystack, ref)
            if w.status != "approved":
                counts["sent"] += 1
            await session.commit()
    for ref in processing:
        try:
            data = await paystack.verify_transfer(ref)
        except PaystackError:
            continue
        async with sessions() as session:
            if await payouts.apply_result(session, ref, data):
                counts["resolved"] += 1
            await session.commit()
    log.info("process_withdrawals %s", counts)
    return counts


async def alert_stale_tables(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Running tables with no result for too long: a lost result keeps players'
    buy-ins in escrow. An admin settles or voids them (/admin/tables/...)."""
    async with sessions() as session:
        minutes = await cfg.get_int(session, "table.running_alert_minutes")
        stale = await table_svc.stale_running(session, minutes)
    if stale:
        log.error(
            "running tables without a result for %d+ min (settle or void in admin): %s",
            minutes,
            [str(t.id) for t in stale],
        )
    return len(stale)


async def check_ledger_integrity(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Every transaction sums to zero, and every account's running balance
    equals the sum of its entries. Anything else is a bug: alert loudly."""
    async with sessions() as session:
        unbalanced = (
            await session.execute(
                select(LedgerEntry.transaction_id, func.sum(LedgerEntry.amount))
                .group_by(LedgerEntry.transaction_id)
                .having(func.sum(LedgerEntry.amount) != 0)
                .limit(50)
            )
        ).all()
        sums = (
            select(LedgerEntry.account_id, func.sum(LedgerEntry.amount).label("total"))
            .group_by(LedgerEntry.account_id)
            .subquery()
        )
        drift = (
            await session.execute(
                select(LedgerAccount.code, LedgerAccount.balance, func.coalesce(sums.c.total, 0))
                .outerjoin(sums, sums.c.account_id == LedgerAccount.id)
                .where(LedgerAccount.balance != func.coalesce(sums.c.total, 0))
                .limit(50)
            )
        ).all()
    report = {
        "unbalanced_transactions": [int(r[0]) for r in unbalanced],
        "balance_drift": [
            {"account": r[0], "balance": int(r[1]), "entries": int(r[2])} for r in drift
        ],
    }
    if unbalanced or drift:
        log.error("LEDGER INTEGRITY FAILURE: %s", report)
    else:
        log.info("ledger integrity ok")
    return report
