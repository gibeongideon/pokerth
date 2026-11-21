"""Sit & Go lifecycle: joining, pulling out, ready check, start, cancel, payout.

Money rules (D-013): a seat costs buy-in + entry fee (+ excise if configured),
shown once, e.g. "$100 + $0.50". The buy-in goes to the table's escrow account,
the fee to ``house:fees``. Nothing is taken during play. At the end the escrow
is paid out by finishing place; withholding tax (if configured) is deducted.

Every money movement goes through ``ledger.post`` with a key derived from the
seat and its join count, so retries never charge or refund twice. All functions
expect the caller to commit (or roll back on TableError).
"""

import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.models import GameTable, StakeTier, TableSeat, User
from app.services import config_registry as cfg
from app.services import ledger, play, referrals, rg
from app.services.game_gateway import GameGateway
from app.services.ledger import Leg

log = logging.getLogger(__name__)

ACTIVE_TABLE = ("open", "ready_check", "running")
ACTIVE_SEAT = ("registered", "playing")
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


class TableError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ------------------------------------------------------------------- pricing


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Price:
    buy_in: int
    fee: int
    excise: int

    @property
    def total(self) -> int:
        return self.buy_in + self.fee + self.excise

    @property
    def label(self) -> str:
        if self.buy_in == 0:
            return "Free"
        text = f"{money(self.buy_in)} + {money(self.fee)}"
        return f"{text} + {money(self.excise)} tax" if self.excise else text


def compute_fee(tier: StakeTier) -> int:
    if tier.buy_in_cents == 0:
        return 0
    if tier.fee_type == "flat":
        fee = int(tier.fee_value)
    else:
        fee = _round_cents(Decimal(tier.buy_in_cents) * Decimal(tier.fee_value) / 100)
    fee = max(fee, tier.fee_min_cents)
    if tier.fee_max_cents is not None:
        fee = min(fee, tier.fee_max_cents)
    return fee


async def price_for(session: AsyncSession, tier: StakeTier) -> Price:
    excise_pct = await cfg.get_decimal(session, "tax.excise_pct")
    excise = _round_cents(Decimal(tier.buy_in_cents) * excise_pct / 100)
    return Price(tier.buy_in_cents, compute_fee(tier), excise)


def validate_tier(tier: StakeTier) -> None:
    """Raise TableError if an admin-defined stake level is inconsistent."""
    problems = []
    if not 2 <= tier.seats <= 10:
        problems.append("seats must be 2-10")
    if not 2 <= tier.min_players <= tier.seats:
        problems.append("min_players must be between 2 and seats")
    if tier.start_mode not in ("when_full", "scheduled"):
        problems.append("start_mode must be when_full or scheduled")
    if tier.fee_type not in ("pct", "flat"):
        problems.append("fee_type must be pct or flat")
    if tier.buy_in_cents < 0 or tier.fee_value < 0 or tier.fee_min_cents < 0:
        problems.append("amounts must not be negative")
    bps = tier.payout_bps
    if (
        not bps
        or any(not isinstance(b, int) or isinstance(b, bool) or b <= 0 for b in bps)
        or sum(bps) != 10_000
    ):
        problems.append("payout_bps must be positive integers summing to 10000")
    elif len(bps) > tier.min_players:
        problems.append("more paid places than min_players")
    if bps and list(bps) != sorted(bps, reverse=True):
        problems.append("payout_bps must not increase with place")
    if problems:
        raise TableError("invalid_tier", "; ".join(problems), 422)


def _snapshot(tier: StakeTier, price: Price) -> dict[str, Any]:
    return {
        "tier_id": tier.id,
        "name": tier.name,
        "buy_in_cents": price.buy_in,
        "fee_cents": price.fee,
        "excise_cents": price.excise,
        "price_label": price.label,
        "seats": tier.seats,
        "min_players": tier.min_players,
        "start_mode": tier.start_mode,
        "payout_bps": list(tier.payout_bps),
        "starting_chips": tier.starting_chips,
        "first_small_blind": tier.first_small_blind,
        "blind_level_minutes": tier.blind_level_minutes,
    }


def _play_entry(table: GameTable) -> int:
    """Demo money a seat costs (free tables only; 0 = none)."""
    return int(table.config.get("play_entry_cents") or 0)


def _price_of(table: GameTable) -> Price:
    c = table.config
    return Price(int(c["buy_in_cents"]), int(c["fee_cents"]), int(c["excise_cents"]))


# ------------------------------------------------------------- table basics


async def open_table(
    session: AsyncSession,
    tier: StakeTier,
    *,
    private: bool = False,
    scheduled_start_at: Any = None,
    created_by: uuid.UUID | None = None,
) -> GameTable:
    if scheduled_start_at is None and tier.start_mode == "scheduled":
        raise TableError("schedule_required", "Scheduled stake levels need a start time.", 422)
    price = await price_for(session, tier)
    config = _snapshot(tier, price)
    if price.total == 0:
        # Free tables are played for demo money (snapshot, like the real price).
        config["play_entry_cents"] = await cfg.get_int(session, "play.table_entry_usd_cents")
    if scheduled_start_at is not None:
        config["start_mode"] = "scheduled"  # starts at its time, not when full
    table = GameTable(
        tier_id=tier.id,
        config=config,
        status="open",
        is_private=private,
        invite_code="".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))
        if private
        else None,
        scheduled_start_at=scheduled_start_at,
        created_by=created_by,
    )
    session.add(table)
    await session.flush()
    return table


async def ensure_open_tables(session: AsyncSession) -> int:
    """Keep one public table taking players for every enabled 'when_full' level."""
    await session.execute(select(func.pg_advisory_xact_lock(7_234_001)))
    tiers = (
        await session.scalars(
            select(StakeTier).where(StakeTier.enabled, StakeTier.start_mode == "when_full")
        )
    ).all()
    opened = 0
    for tier in tiers:
        exists = await session.scalar(
            select(GameTable.id)
            .where(GameTable.tier_id == tier.id, GameTable.status == "open")
            .where(GameTable.is_private.is_(False))
            .limit(1)
        )
        if exists is None:
            await open_table(session, tier)
            opened += 1
    return opened


async def _lock_table(session: AsyncSession, table_id: uuid.UUID) -> GameTable:
    table = await session.scalar(
        select(GameTable)
        .where(GameTable.id == table_id)
        .with_for_update()
        .execution_options(populate_existing=True)  # never act on a stale cached row
    )
    if table is None:
        raise TableError("not_found", "Table not found.", 404)
    return table


async def check_user_can_create(session: AsyncSession, tier: StakeTier) -> None:
    """Player-created tables: free stakes always; paid only if the setting allows."""
    if tier.buy_in_cents > 0 and not await cfg.get_bool(session, "tables.user_created_paid"):
        raise TableError(
            "paid_tables_quick_play_only",
            "For now, paid stakes are played through Quick play. Create a free table instead.",
            403,
        )


async def has_active_seat(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Seated (or registered) at a table that hasn't finished."""
    found = await session.scalar(
        select(TableSeat.id)
        .join(GameTable, GameTable.id == TableSeat.table_id)
        .where(TableSeat.user_id == user_id, TableSeat.status.in_(ACTIVE_SEAT))
        .where(GameTable.status.in_(ACTIVE_TABLE))
        .limit(1)
    )
    return found is not None


async def _seats(session: AsyncSession, table_id: uuid.UUID, *statuses: str) -> list[TableSeat]:
    return list(
        (
            await session.scalars(
                select(TableSeat)
                .where(TableSeat.table_id == table_id, TableSeat.status.in_(statuses))
                .order_by(TableSeat.joined_at)
            )
        ).all()
    )


# ------------------------------------------------------------------- money


def _charge_legs(table: GameTable, user_id: uuid.UUID) -> list[Leg]:
    p = _price_of(table)
    legs = [Leg(ledger.user_available(user_id), -p.total)]
    if p.buy_in:
        legs.append(Leg(ledger.table_escrow(table.id), p.buy_in))
    if p.fee:
        legs.append(Leg(ledger.HOUSE_FEES, p.fee))
    if p.excise:
        legs.append(Leg(ledger.TAX_EXCISE, p.excise))
    return legs


async def _refund(
    session: AsyncSession, table: GameTable, seat: TableSeat, why: str, keep_fee: bool = False
) -> None:
    entry = _play_entry(table)
    if entry:
        await ledger.post(
            session,
            idempotency_key=f"{why}-play:{seat.id}:{seat.join_count}",
            kind="play_refund",
            legs=[
                Leg(ledger.user_play(seat.user_id), entry),
                Leg(ledger.table_play(table.id), -entry),
            ],
            memo=f"demo money back ({why})",
            meta={"table_id": str(table.id)},
        )
    p = _price_of(table)
    fee_back = 0 if keep_fee else p.fee
    total = p.buy_in + fee_back + p.excise
    if total == 0:
        return
    legs = [Leg(ledger.user_available(seat.user_id), total)]
    if p.buy_in:
        legs.append(Leg(ledger.table_escrow(table.id), -p.buy_in))
    if fee_back:
        legs.append(Leg(ledger.HOUSE_FEES, -fee_back))
    if p.excise:
        legs.append(Leg(ledger.TAX_EXCISE, -p.excise))
    await ledger.post(
        session,
        idempotency_key=f"{why}:{seat.id}:{seat.join_count}",
        kind="refund",
        legs=legs,
        memo=f"refund ({why})",
        meta={"table_id": str(table.id)},
        actor_id=seat.user_id,
    )


# -------------------------------------------------------------- player moves


async def _check_join_gates(session: AsyncSession, user: User, table: GameTable) -> None:
    # One join per player at a time, so the table limit and RG checks below
    # can't be raced by joining two tables in parallel.
    await session.execute(
        select(func.pg_advisory_xact_lock(7_234_002, func.hashtext(str(user.id))))
    )
    if not user.username:
        raise TableError("username_required", "Choose a username before joining a table.", 403)
    if _price_of(table).total > 0:
        if not await cfg.get_bool(session, "real_money_enabled"):
            raise TableError("real_money_disabled", "Real-money play is not available yet.", 403)
        if user.terms_accepted_at is None:
            raise TableError("terms_required", "Accept the terms and confirm you are 18+.", 403)
        needed = await cfg.get_int(session, "kyc.play_min_tier")
        if user.kyc_tier < needed:
            raise TableError("kyc_required", f"Verify your identity (level {needed}).", 403)
        try:
            await rg.check_play(session, user, _price_of(table).total)
        except rg.RgBlockedError as exc:
            raise TableError(exc.code, str(exc), 403) from exc
    limit = await cfg.get_int(session, "table.max_concurrent_per_user")
    active = await session.scalar(
        select(func.count())
        .select_from(TableSeat)
        .join(GameTable, GameTable.id == TableSeat.table_id)
        .where(TableSeat.user_id == user.id, TableSeat.status.in_(ACTIVE_SEAT))
        .where(GameTable.status.in_(ACTIVE_TABLE))
    )
    if (active or 0) >= limit:
        raise TableError("too_many_tables", f"You can be in at most {limit} tables at once.", 409)


async def join(
    session: AsyncSession,
    gateway: GameGateway,
    table_id: uuid.UUID,
    user: User,
    invite_code: str | None = None,
) -> TableSeat:
    table = await _lock_table(session, table_id)
    if table.status != "open":
        raise TableError("table_not_open", "This table is no longer taking players.", 409)
    opens = table.config.get("registration_opens_at")
    if opens and utcnow() < datetime.fromisoformat(opens):
        raise TableError("registration_not_open", f"Registration opens at {opens}.", 409)
    if table.is_private and not hmac.compare_digest(
        (invite_code or "").upper(), table.invite_code or ""
    ):
        raise TableError("invite_required", "This is a private table; you need its code.", 403)

    seat = await session.scalar(
        select(TableSeat).where(TableSeat.table_id == table.id, TableSeat.user_id == user.id)
    )
    if seat is not None and seat.status == "registered":
        return seat  # joining twice is a no-op

    await _check_join_gates(session, user, table)
    registered = await _seats(session, table.id, "registered")
    if len(registered) >= table.config["seats"]:
        raise TableError("table_full", "This table is full.", 409)

    now = utcnow()
    if seat is None:
        seat = TableSeat(
            table_id=table.id, user_id=user.id, status="registered", join_count=1, joined_at=now
        )
        session.add(seat)
        await session.flush()
    else:
        seat.join_count += 1
        seat.status, seat.joined_at, seat.ready_at = "registered", now, None

    if _price_of(table).total > 0:
        try:
            await ledger.post(
                session,
                idempotency_key=f"buyin:{seat.id}:{seat.join_count}",
                kind="buy_in",
                legs=_charge_legs(table, user.id),
                memo=f"{table.config['name']} {table.config['price_label']}",
                meta={"table_id": str(table.id)},
                actor_id=user.id,
            )
        except ledger.InsufficientFundsError as exc:
            raise TableError(
                "insufficient_funds",
                f"You need {money(_price_of(table).total)} in your wallet to join.",
            ) from exc

    entry = _play_entry(table)
    if entry:
        await play.ensure_started(session, user.id)
        try:
            await ledger.post(
                session,
                idempotency_key=f"play-buyin:{seat.id}:{seat.join_count}",
                kind="play_buy_in",
                legs=[
                    Leg(ledger.user_play(user.id), -entry),
                    Leg(ledger.table_play(table.id), entry),
                ],
                memo=f"{table.config['name']} (demo money)",
                meta={"table_id": str(table.id)},
                actor_id=user.id,
            )
        except ledger.InsufficientFundsError as exc:
            raise TableError(
                "out_of_demo_money",
                f"You need {money(entry)} demo money for this table. Refill it in your wallet.",
                409,
            ) from exc

    if table.config["start_mode"] == "when_full" and len(registered) + 1 == table.config["seats"]:
        await _begin_ready_check(session, table)
        await ensure_open_tables(session)
    return seat


async def leave(session: AsyncSession, table_id: uuid.UUID, user: User) -> None:
    """Pull out and get everything back, within the grace window."""
    table = await _lock_table(session, table_id)
    seat = await session.scalar(
        select(TableSeat).where(TableSeat.table_id == table.id, TableSeat.user_id == user.id)
    )
    if seat is None or seat.status != "registered":
        raise TableError("not_registered", "You are not registered at this table.", 404)
    if table.status != "open":
        raise TableError("table_locked", "The table is starting; you can't pull out now.", 409)
    grace = await cfg.get_int(session, "table.unregister_grace_seconds")
    if utcnow() > seat.joined_at + timedelta(seconds=grace):
        raise TableError("pull_out_closed", "The free pull-out window has passed.", 409)
    await _refund(session, table, seat, "unregister")
    seat.status = "left"


async def leave_all_open(session: AsyncSession, user: User) -> int:
    """Pull a player out of every table still taking players, with full refunds
    and no grace-window check (used on self-exclusion)."""
    table_ids = (
        await session.scalars(
            select(TableSeat.table_id)
            .join(GameTable, GameTable.id == TableSeat.table_id)
            .where(TableSeat.user_id == user.id, TableSeat.status == "registered")
            .where(GameTable.status == "open")
        )
    ).all()
    for table_id in table_ids:
        table = await _lock_table(session, table_id)
        seat = await session.scalar(
            select(TableSeat).where(TableSeat.table_id == table.id, TableSeat.user_id == user.id)
        )
        if table.status == "open" and seat is not None and seat.status == "registered":
            await _refund(session, table, seat, "exclusion")
            seat.status = "left"
    return len(table_ids)


async def _begin_ready_check(session: AsyncSession, table: GameTable) -> None:
    secs = await cfg.get_int(session, "table.ready_check_seconds")
    table.status = "ready_check"
    table.ready_deadline = utcnow() + timedelta(seconds=secs)
    for seat in await _seats(session, table.id, "registered"):
        seat.ready_at = None


async def mark_ready(
    session: AsyncSession, gateway: GameGateway, table_id: uuid.UUID, user: User
) -> GameTable:
    table = await _lock_table(session, table_id)
    if table.status != "ready_check":
        raise TableError("no_ready_check", "This table is not waiting for players.", 409)
    if _price_of(table).total > 0 and rg.is_excluded(user):
        raise TableError("self_excluded", "Real-money play is paused for you.", 403)
    seats = await _seats(session, table.id, "registered")
    mine = next((s for s in seats if s.user_id == user.id), None)
    if mine is None:
        raise TableError("not_registered", "You are not registered at this table.", 404)
    mine.ready_at = mine.ready_at or utcnow()
    if all(s.ready_at for s in seats):
        await _start(session, gateway, table, seats)
    return table


async def _start(
    session: AsyncSession, gateway: GameGateway, table: GameTable, seats: list[TableSeat]
) -> None:
    users = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_([s.user_id for s in seats])))
        ).all()
    }
    placement = await gateway.create_game(
        table.id,
        table.config,
        [{"user_id": str(s.user_id), "username": users[s.user_id].username or ""} for s in seats],
    )
    table.status = "running"
    table.started_at = utcnow()
    table.ready_deadline = None
    table.game_ref, table.ws_url = placement.game_ref, placement.ws_url
    for seat in seats:
        seat.status = "playing"


async def cancel(session: AsyncSession, table: GameTable, reason: str) -> None:
    """Cancel a table that hasn't started and refund everyone in full."""
    if table.status not in ("open", "ready_check"):
        raise TableError("cannot_cancel", "Only tables that haven't started can be cancelled.", 409)
    for seat in await _seats(session, table.id, "registered"):
        await _refund(session, table, seat, "cancel")
        seat.status = "left"
    table.status = "cancelled"
    table.cancel_reason = reason
    table.ready_deadline = None


# ------------------------------------------------------------------- timers


async def tick(session: AsyncSession, gateway: GameGateway) -> dict[str, int]:
    """Run by the worker every few seconds: ready-check timeouts, scheduled
    starts, and keeping an open table per stake level."""
    now = utcnow()
    counts = {"ready_timeouts": 0, "started": 0, "cancelled": 0, "opened": 0}

    expired = (
        await session.scalars(
            select(GameTable)
            .where(GameTable.status == "ready_check", GameTable.ready_deadline < now)
            .with_for_update(skip_locked=True)
        )
    ).all()
    keep_fee = await cfg.get(session, "table.no_show_policy") == "forfeit_fee"
    for table in expired:
        counts["ready_timeouts"] += 1
        seats = await _seats(session, table.id, "registered")
        ready = [s for s in seats if s.ready_at]
        for seat in seats:
            if not seat.ready_at:
                await _refund(session, table, seat, "noshow", keep_fee=keep_fee)
                seat.status = "removed"
        if table.config["start_mode"] == "scheduled":
            if len(ready) >= table.config["min_players"]:
                await _start(session, gateway, table, ready)
                counts["started"] += 1
            else:
                await cancel(session, table, "not_enough_ready")
                counts["cancelled"] += 1
        else:
            table.status, table.ready_deadline = "open", None
            for seat in ready:
                seat.ready_at = None

    due = (
        await session.scalars(
            select(GameTable)
            .where(GameTable.status == "open", GameTable.scheduled_start_at <= now)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for table in due:
        if len(await _seats(session, table.id, "registered")) >= table.config["min_players"]:
            await _begin_ready_check(session, table)
        else:
            await cancel(session, table, "not_enough_players")
            counts["cancelled"] += 1

    # A table that never fills must not hold buy-ins forever: after
    # table.open_max_minutes from the first join, cancel it with full refunds.
    open_max = await cfg.get_int(session, "table.open_max_minutes")
    if open_max:
        oldest = (
            select(TableSeat.table_id, func.min(TableSeat.joined_at).label("first"))
            .where(TableSeat.status == "registered")
            .group_by(TableSeat.table_id)
            .subquery()
        )
        stale = (
            await session.scalars(
                select(GameTable)
                .join(oldest, oldest.c.table_id == GameTable.id)
                .where(GameTable.status == "open", GameTable.scheduled_start_at.is_(None))
                .where(oldest.c.first < now - timedelta(minutes=open_max))
                .with_for_update(of=GameTable, skip_locked=True)
            )
        ).all()
        for table in stale:
            await cancel(session, table, "did_not_fill")
            counts["cancelled"] += 1

    counts["opened"] = await ensure_open_tables(session)
    return counts


async def void_running(session: AsyncSession, table_id: uuid.UUID, reason: str) -> GameTable:
    """Admin: a running game whose result is lost. Everyone seated gets their
    whole entry back (buy-in, fee and tax); the table is cancelled."""
    table = await _lock_table(session, table_id)
    if table.status != "running":
        raise TableError("table_not_running", "Only running tables can be voided.", 409)
    for seat in await _seats(session, table.id, "playing"):
        await _refund(session, table, seat, "void")
        seat.status = "left"
    leftover = await ledger.balance(session, ledger.table_escrow(table.id))
    if leftover:
        raise TableError("escrow_mismatch", f"Escrow still holds {leftover} after refunds.", 500)
    table.status, table.cancel_reason = "cancelled", reason[:200]
    return table


async def stale_running(session: AsyncSession, minutes: int) -> list[GameTable]:
    """Running tables with no result for longer than ``minutes`` (lost result?)."""
    return list(
        (
            await session.scalars(
                select(GameTable)
                .where(GameTable.status == "running")
                .where(GameTable.started_at < utcnow() - timedelta(minutes=minutes))
                .limit(200)
            )
        ).all()
    )


# ------------------------------------------------------------------ results


def split_prizes(pool: int, payout_bps: list[int], players: int) -> list[int]:
    """Prize per finishing place. With fewer players than paid places the
    remaining shares are scaled up; rounding leftovers go to first place."""
    bps = payout_bps[:players]
    total_bps = sum(bps)
    if not bps or total_bps <= 0:
        return []
    prizes = [pool * b // total_bps for b in bps]
    prizes[0] += pool - sum(prizes)
    return prizes


async def settle(
    session: AsyncSession,
    table_id: uuid.UUID,
    finishing_order: list[uuid.UUID],
    places: dict[uuid.UUID, int] | None = None,
) -> GameTable:
    """Pay out a finished game. ``finishing_order`` = user ids, winner first.
    Calling it again for a finished table is a no-op."""
    table = await _lock_table(session, table_id)
    if table.status == "finished":
        return table
    if table.status != "running":
        raise TableError("table_not_running", "This table is not running.", 409)
    playing = await _seats(session, table.id, "playing")
    seats = {s.user_id: s for s in playing}
    if len(set(finishing_order)) != len(finishing_order) or not set(finishing_order) <= set(seats):
        raise TableError("bad_result", "The result lists unknown or repeated players.", 422)
    # Seated players the game server never saw (they didn't connect) finish last,
    # in the order they joined - the same as a no-show forfeiting the seat.
    finishing_order = list(finishing_order) + [
        s.user_id for s in playing if s.user_id not in set(finishing_order)
    ]

    pool = await ledger.balance(session, ledger.table_escrow(table.id))
    # Guaranteed prize pool: the house tops up the difference (D-023).
    topup = max(0, int(table.config.get("guaranteed_prize_cents") or 0) - pool)
    total_prizes = pool + topup
    prizes = split_prizes(total_prizes, list(table.config["payout_bps"]), len(finishing_order))
    withholding_pct = await cfg.get_decimal(session, "tax.withholding_pct")

    legs = [Leg(ledger.table_escrow(table.id), -pool)] if pool else []
    if topup:
        legs.append(Leg(ledger.PROMOTIONS, -topup))
    withheld_total = 0
    for place, user_id in enumerate(finishing_order, start=1):
        gross = prizes[place - 1] if place <= len(prizes) else 0
        withheld = _round_cents(Decimal(gross) * withholding_pct / 100)
        net = gross - withheld
        withheld_total += withheld
        if net:
            legs.append(Leg(ledger.user_available(user_id), net))
        seat = seats[user_id]
        seat.status, seat.finish_position, seat.prize_cents = "finished", place, net
    if withheld_total:
        legs.append(Leg(ledger.TAX_WITHHOLDING, withheld_total))
    if total_prizes:
        await ledger.post(
            session,
            idempotency_key=f"settle:{table.id}",
            kind="prize",
            legs=legs,
            memo=f"{table.config['name']} prizes",
            meta={"table_id": str(table.id), "order": [str(u) for u in finishing_order]},
        )
    await _settle_play(session, table, finishing_order, places or {})
    if _price_of(table).total > 0:
        for user_id in finishing_order:
            await referrals.maybe_reward(session, user_id)
    table.status = "finished"
    table.finished_at = utcnow()
    return table


async def _settle_play(
    session: AsyncSession,
    table: GameTable,
    finishing_order: list[uuid.UUID],
    places: dict[uuid.UUID, int],
) -> None:
    """Pay out a free table's demo pot. Practice (computer players): the
    human wins the computer players' entries too - but only by finishing 1st."""
    pot = await ledger.balance(session, ledger.table_play(table.id))
    entry = _play_entry(table)
    if not entry and not pot:
        return
    bots = int(table.config.get("bots") or 0)
    legs: list[Leg] = [Leg(ledger.table_play(table.id), -pot)] if pot else []
    if bots:
        human = finishing_order[0] if finishing_order else None
        if human is not None and places.get(human) == 1:
            prize = entry * (bots + 1)
            legs += [Leg(ledger.PLAY_BANK, -(prize - pot)), Leg(ledger.user_play(human), prize)]
        elif pot:
            legs.append(Leg(ledger.PLAY_BANK, pot))  # the computer won
    else:
        prizes = split_prizes(pot, list(table.config["payout_bps"]), len(finishing_order))
        for place, user_id in enumerate(finishing_order, start=1):
            amount = prizes[place - 1] if place <= len(prizes) else 0
            if amount:
                legs.append(Leg(ledger.user_play(user_id), amount))
    legs = [leg for leg in legs if leg.amount]
    if legs:
        await ledger.post(
            session,
            idempotency_key=f"settle-play:{table.id}",
            kind="play_prize",
            legs=legs,
            memo=f"{table.config['name']} (demo money)",
            meta={"table_id": str(table.id), "places": {str(k): v for k, v in places.items()}},
        )


async def quit_practice(session: AsyncSession, table_id: uuid.UUID, user: User) -> GameTable:
    """Leave a practice game early: it counts as finishing last (the demo
    entry is lost) and the table is finished, so the player can play again."""
    table = await _lock_table(session, table_id)
    if not table.config.get("bots") or table.status != "running":
        raise TableError("not_practice", "Only a running practice game can be left early.", 409)
    if user.id not in {s.user_id for s in await _seats(session, table.id, "playing")}:
        raise TableError("not_registered", "You are not playing at this table.", 404)
    last = int(table.config["bots"]) + 1
    return await settle(session, table.id, [user.id], {user.id: last})


async def start_practice(
    session: AsyncSession, gateway: GameGateway, user: User, bots: int = 5
) -> GameTable:
    """Free game against computer players, starting now. Virtual chips only:
    built on the free stake level, never on a paid one."""
    tier = await session.scalar(
        select(StakeTier)
        .where(StakeTier.enabled, StakeTier.buy_in_cents == 0)
        .order_by(StakeTier.sort_order)
        .limit(1)
    )
    if tier is None:
        raise TableError("not_found", "Free play is not available right now.", 404)
    if not 1 <= bots <= 9:
        raise TableError("bad_request", "Choose between 1 and 9 computer players.", 422)
    table = await open_table(session, tier, private=True, created_by=user.id)
    if _price_of(table).total != 0:
        raise TableError("not_free", "Practice tables must be free.", 409)
    table.title = "Practice vs computer"
    table.config = {
        **table.config,
        "name": "Practice",
        "start_mode": "practice",
        "seats": 1,
        "min_players": 1,
        "payout_bps": [10_000],
        "bots": bots,
    }
    seat = await join(session, gateway, table.id, user, table.invite_code)
    await _start(session, gateway, table, [seat])
    return table


# --------------------------------------------------------------------- views


async def quick_play(
    session: AsyncSession, gateway: GameGateway, tier_id: int, user: User
) -> TableSeat:
    """Seat the player at the fullest public table of this level that has room."""
    tier = await session.get(StakeTier, tier_id)
    if tier is None or not tier.enabled or tier.start_mode != "when_full":
        raise TableError("not_found", "That stake level is not available for quick play.", 404)
    counts = (
        select(TableSeat.table_id, func.count().label("n"))
        .where(TableSeat.status == "registered")
        .group_by(TableSeat.table_id)
        .subquery()
    )
    candidates = (
        await session.execute(
            select(GameTable.id, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.table_id == GameTable.id)
            .where(GameTable.tier_id == tier.id, GameTable.status == "open")
            .where(GameTable.is_private.is_(False))
            .order_by(func.coalesce(counts.c.n, 0).desc(), GameTable.created_at)
        )
    ).all()
    for table_id, _n in candidates:
        try:
            return await join(session, gateway, table_id, user)
        except TableError as exc:
            if exc.code not in ("table_full", "table_not_open"):
                raise
    table = await open_table(session, tier)
    return await join(session, gateway, table.id, user)


def game_server_cfg(table: GameTable, players: int) -> dict[str, Any]:
    """Table settings carried in seat tokens for the game server (D-025)."""
    c = table.config
    return {
        "players": players,
        "chips": int(c.get("starting_chips") or 3000),
        "sb": int(c.get("first_small_blind") or 10),
        "blind_minutes": int(c.get("blind_level_minutes") or 5),
        "title": (table.title or c["name"])[:60],
        # Practice tables: the game server fills the other seats with computer players.
        "bots": int(c.get("bots") or 0),
    }


async def table_view(
    session: AsyncSession, table: GameTable, viewer: uuid.UUID | None = None
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(TableSeat, User.username)
            .join(User, User.id == TableSeat.user_id)
            .where(TableSeat.table_id == table.id)
            .order_by(TableSeat.joined_at)
        )
    ).all()
    grace = await cfg.get_int(session, "table.unregister_grace_seconds")
    now = utcnow()
    seats, me = [], None
    for seat, username in rows:
        if seat.status in ("left", "removed"):
            continue
        item = {
            "username": username,
            "status": seat.status,
            "ready": seat.ready_at is not None,
            "finish_position": seat.finish_position,
            "prize_cents": seat.prize_cents,
        }
        seats.append(item)
        if seat.user_id == viewer:
            pull_out_until = seat.joined_at + timedelta(seconds=grace)
            me = {
                **item,
                "can_pull_out": table.status == "open"
                and seat.status == "registered"
                and now <= pull_out_until,
                "pull_out_seconds_left": max(0, int((pull_out_until - now).total_seconds())),
            }
    c = table.config
    players = len([s for s in seats if s["status"] in ("registered", "playing", "finished")])
    return {
        "id": str(table.id),
        "status": table.status,
        "name": c["name"],
        "price_label": c["price_label"],
        "buy_in_cents": c["buy_in_cents"],
        "fee_cents": c["fee_cents"],
        "excise_cents": c["excise_cents"],
        "seats_total": c["seats"],
        "min_players": c["min_players"],
        "players": players,
        "prize_pool_cents": max(c["buy_in_cents"] * players, c.get("guaranteed_prize_cents") or 0),
        "guaranteed_prize_cents": c.get("guaranteed_prize_cents"),
        "registration_opens_at": c.get("registration_opens_at"),
        "payout_bps": c["payout_bps"],
        "start_mode": c["start_mode"],
        "bots": int(c.get("bots") or 0),
        "is_private": table.is_private,
        "title": table.title,
        "message": table.message,
        "is_organizer": viewer is not None and table.created_by == viewer,
        "invite_code": table.invite_code
        if table.is_private and (me or (viewer is not None and table.created_by == viewer))
        else None,
        "scheduled_start_at": table.scheduled_start_at.isoformat()
        if table.scheduled_start_at
        else None,
        "ready_deadline": table.ready_deadline.isoformat() if table.ready_deadline else None,
        "seats": seats,
        "me": me,
    }
