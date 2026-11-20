"""Double-entry ledger (D-008).

Every money movement is one JournalTransaction whose entries sum to zero.
Amounts are signed integers in minor units (USD cents). For a user account a
positive entry increases what the house owes the user.

``LedgerAccount.balance`` is a running total maintained only by
``app.services.ledger.post`` inside the same DB transaction as the entries,
under a row lock; reconciliation checks it equals the sum of entries.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint("allow_negative OR balance >= 0", name="balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # e.g. "user:<uuid>:available", "house:fees", "paystack:clearing"
    code: Mapped[str] = mapped_column(String(100), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    # True only for house/clearing accounts that mirror external money.
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JournalTransaction(Base):
    __tablename__ = "journal_transactions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Same key = same money movement; posting it twice is a no-op.
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    # deposit | p2p_transfer | buy_in | prize | fee | refund | withdrawal | adjustment
    kind: Mapped[str] = mapped_column(String(32), index=True)
    memo: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint("amount <> 0", name="amount_non_zero"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("journal_transactions.id"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ledger_accounts.id"), index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
