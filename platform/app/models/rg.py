"""Responsible-gaming limits set by the player (Phase 5.8).

A tighter limit applies at once. A looser one (or removing it) is stored as
pending and applies after ``rg.limit_increase_delay_hours``.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RgLimit(Base):
    __tablename__ = "rg_limits"
    __table_args__ = (UniqueConstraint("user_id", "kind", "period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # deposit | loss
    period: Mapped[str] = mapped_column(String(8))  # day | week | month (rolling)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)  # None = no limit
    pending_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    # Set when a looser limit is waiting; pending_amount_cents None then means "remove".
    pending_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
