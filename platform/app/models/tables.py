"""Stake levels (D-016) and Sit & Go tables.

Table lifecycle:
    open --(full, when_full)--> ready_check --(all ready)--> running --> finished
    open --(scheduled time, enough players)--> ready_check
    open/ready_check --(scheduled, too few players)--> cancelled (everyone refunded)
    ready_check --(timeout)--> no-shows removed; back to open (when_full),
                               or start / cancel (scheduled)

Seat status: registered -> playing -> finished, or left (pulled out / refunded),
or removed (missed the ready check).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StakeTier(Base):
    __tablename__ = "stake_tiers"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    buy_in_cents: Mapped[int] = mapped_column(BigInteger)  # 0 = free play
    fee_type: Mapped[str] = mapped_column(String(8), default="pct")  # pct | flat
    # pct: percent of buy-in (0.5 = 0.5 %); flat: cents
    fee_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    fee_min_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_max_cents: Mapped[int | None] = mapped_column(BigInteger)
    seats: Mapped[int] = mapped_column(Integer)  # 2..10 (PokerTH limit)
    min_players: Mapped[int] = mapped_column(Integer)
    start_mode: Mapped[str] = mapped_column(String(16), default="when_full")  # | scheduled
    # Prize split by finishing place, in basis points summing to 10000.
    payout_bps: Mapped[list[int]] = mapped_column(JSONB)
    starting_chips: Mapped[int] = mapped_column(Integer, default=3000)
    first_small_blind: Mapped[int] = mapped_column(Integer, default=10)
    blind_level_minutes: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GameTable(Base):
    __tablename__ = "game_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tier_id: Mapped[int] = mapped_column(Integer, ForeignKey("stake_tiers.id"), index=True)
    # Copy of the tier (with computed price) when the table opened, so admin
    # changes to the tier never affect a table already taking players.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), index=True, default="open")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_code: Mapped[str | None] = mapped_column(String(12), unique=True)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Organized games: shown to invitees ("Friday night poker").
    title: Mapped[str | None] = mapped_column(String(80))
    message: Mapped[str | None] = mapped_column(String(500))
    # Set when the game server has the game.
    game_ref: Mapped[str | None] = mapped_column(String(64))
    ws_url: Mapped[str | None] = mapped_column(String(255))
    cancel_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TableSeat(Base):
    __tablename__ = "table_seats"
    __table_args__ = (UniqueConstraint("table_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_tables.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    # Bumped on every (re)join; part of the ledger idempotency keys.
    join_count: Mapped[int] = mapped_column(Integer, default=1)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finish_position: Mapped[int | None] = mapped_column(Integer)
    prize_cents: Mapped[int | None] = mapped_column(BigInteger)
