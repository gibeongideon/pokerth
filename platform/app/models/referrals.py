"""Referrals (Phase 5.6): status pending -> rewarded (or void).

The bonus is paid when the referred player finishes their first paid game,
not at sign-up or deposit, so fake sign-ups earn nothing.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    referred_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    referrer_bonus_cents: Mapped[int | None] = mapped_column(BigInteger)
    referred_bonus_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayerInvite(Base):
    """'Join me on Felt Kings' sent to an email address. The invite is tied to
    the email, so whenever that address signs up - through the link or not -
    the inviter gets the referral and the two become friends."""

    __tablename__ = "player_invites"
    __table_args__ = (
        UniqueConstraint("inviter_id", "email", name="player_invites_inviter_email_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | joined
    joined_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
