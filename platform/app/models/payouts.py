"""Withdrawals to M-Pesa through Paystack Transfers (Phase 4).

Withdrawal status:
    awaiting_confirmation --(email code)--> pending_review | approved
    pending_review --(admin)--> approved | rejected
    approved --(transfer sent)--> processing --(webhook/verify)--> success | failed | reversed
    awaiting_confirmation / pending_review --(player)--> cancelled
    awaiting_confirmation --(code expires)--> expired

Money leaves the wallet when the player confirms (into ``payouts:pending``)
and comes back in full on rejected / cancelled / failed / reversed.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PayoutDestination(Base):
    __tablename__ = "payout_destinations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="mpesa")
    account_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(16))  # E.164
    # Paystack transfer recipient, created on first payout.
    recipient_code: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payout_destinations.id")
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    # Leaves the wallet; the player receives amount - fee, converted to KES.
    amount_usd_cents: Mapped[int] = mapped_column(BigInteger)
    fee_usd_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    payout_currency: Mapped[str] = mapped_column(String(3), default="KES")
    payout_amount: Mapped[int] = mapped_column(BigInteger)  # KES subunits, whole shillings
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    review_reasons: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    # Email step-up: hashed 6-digit code.
    otp_hash: Mapped[str | None] = mapped_column(String(64))
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    transfer_code: Mapped[str | None] = mapped_column(String(64))
    send_attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
