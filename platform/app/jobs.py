"""Background jobs. Plain async functions so tests can call them directly;
``app/worker.py`` schedules them with Celery beat."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import Deposit, Withdrawal
from app.services import config_registry as cfg
from app.services import payments as pay
from app.services import payouts
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
        stale = (
            await session.scalars(
                select(Withdrawal).where(
                    Withdrawal.status == "awaiting_confirmation", Withdrawal.otp_expires_at < now
                )
            )
        ).all()
        for w in stale:
            w.status = "expired"
            counts["expired"] += 1
        await session.commit()

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
