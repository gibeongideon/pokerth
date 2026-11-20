import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Deposit(Base):
    """A Paystack charge that credits a wallet once confirmed.

    status: pending -> success | failed | abandoned | expired | mismatch
    ``mismatch`` = Paystack reported success but amount/currency differ from
    what we asked for; never credited, flagged for manual review.
    """

    __tablename__ = "deposits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    payer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    # Whose wallet gets the money; differs from payer for fund-a-friend.
    beneficiary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))  # card | mpesa
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending")
    credit_usd_cents: Mapped[int] = mapped_column(BigInteger)
    # What Paystack charges, in its subunits (USD cents or KES cents).
    charge_currency: Mapped[str] = mapped_column(String(3))
    charge_amount: Mapped[int] = mapped_column(BigInteger)
    # KES per USD used for this deposit (None for USD card charges).
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    phone: Mapped[str | None] = mapped_column(String(16))
    paystack_id: Mapped[str | None] = mapped_column(String(32))
    gateway_response: Mapped[str | None] = mapped_column(Text)
    journal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_transactions.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    """Every webhook we accept, stored before processing. The unique key makes
    redelivery idempotent; failures keep the row with the error for retries."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    event_key: Mapped[str] = mapped_column(String(160))
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
