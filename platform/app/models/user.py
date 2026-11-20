import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stored lower-cased; the login identity.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Public table name, lower-case [a-z0-9_]{3,20}; chosen after first sign-in.
    username: Mapped[str | None] = mapped_column(String(20), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(64))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # E.164 (+2547XXXXXXXX), used for M-Pesa.
    phone: Mapped[str | None] = mapped_column(String(16))
    # 0 = email only, 1 = ID number verified, 2 = selfie + liveness (D-014).
    kyc_tier: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # active | suspended | self_excluded
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Terms + responsible-gaming rules accepted and 18+ confirmed, in one step.
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Shareable code for referral links; created on first request.
    referral_code: Mapped[str | None] = mapped_column(String(12), unique=True)
    # Self-exclusion (Phase 5.8): no deposits or paid play until then.
    excluded_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Play-time reminder interval the apps show; None = off.
    reality_check_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
