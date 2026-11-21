import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import AdminUser, PaystackDep, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import (
    Deposit,
    GameTable,
    JournalTransaction,
    LedgerAccount,
    LedgerEntry,
    StakeTier,
    User,
    Withdrawal,
)
from app.services import auth as auth_svc
from app.services import config_registry as cfg
from app.services import ledger, payouts
from app.services import tables as table_svc
from app.services.payments import PaymentError, deposit_view

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class SettingUpdate(BaseModel):
    value: Any


class KycTierUpdate(BaseModel):
    kyc_tier: int = Field(ge=0, le=2)


@router.get("/settings")
async def list_settings(_admin: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    return await cfg.all_settings(session)


@router.put("/settings/{key}")
async def update_setting(
    key: str, body: SettingUpdate, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    try:
        await cfg.set_value(session, key, body.value, admin.id)
    except cfg.SettingError as exc:
        await session.rollback()
        raise ApiError(422, "invalid_setting", str(exc)) from exc
    await session.commit()
    return next(s for s in await cfg.all_settings(session) if s["key"] == key)


@router.put("/users/{user_id}/kyc-tier")
async def set_kyc_tier(
    user_id: uuid.UUID, body: KycTierUpdate, admin: AdminUser, session: SessionDep
) -> UserOut:
    """Manual KYC override until the Smile ID integration lands."""
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "User not found.")
    if user.id == admin.id:
        raise ApiError(409, "self_change", "Another admin must change your verification level.")
    user.kyc_tier = body.kyc_tier
    await session.commit()
    return user_out(user)


# ------------------------------------------------------------- stake levels (D-016)


class StakeTierIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    buy_in_cents: int = Field(ge=0)
    fee_type: Literal["pct", "flat"] = "pct"
    fee_value: Decimal = Field(default=Decimal("0.5"), ge=0)
    fee_min_cents: int = Field(default=0, ge=0)
    fee_max_cents: int | None = Field(default=None, ge=0)
    seats: int = 6
    min_players: int = 2
    start_mode: Literal["when_full", "scheduled"] = "when_full"
    payout_bps: list[int] = [6500, 3500]
    starting_chips: int = Field(default=3000, gt=0)
    first_small_blind: int = Field(default=10, gt=0)
    blind_level_minutes: int = Field(default=5, gt=0)
    enabled: bool = True
    sort_order: int = 0


def _tier_out(t: StakeTier) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "buy_in_cents": t.buy_in_cents,
        "fee_type": t.fee_type,
        "fee_value": str(t.fee_value),
        "fee_min_cents": t.fee_min_cents,
        "fee_max_cents": t.fee_max_cents,
        "fee_cents": table_svc.compute_fee(t),
        "seats": t.seats,
        "min_players": t.min_players,
        "start_mode": t.start_mode,
        "payout_bps": t.payout_bps,
        "starting_chips": t.starting_chips,
        "first_small_blind": t.first_small_blind,
        "blind_level_minutes": t.blind_level_minutes,
        "enabled": t.enabled,
        "sort_order": t.sort_order,
    }


@router.get("/stake-tiers")
async def list_tiers(_admin: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.scalars(select(StakeTier).order_by(StakeTier.sort_order, StakeTier.id))
    return [_tier_out(t) for t in rows.all()]


@router.post("/stake-tiers", status_code=201)
async def create_tier(body: StakeTierIn, _admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    tier = StakeTier(**body.model_dump())
    try:
        table_svc.validate_tier(tier)
    except table_svc.TableError as exc:
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    session.add(tier)
    await session.commit()
    return _tier_out(tier)


@router.put("/stake-tiers/{tier_id}")
async def update_tier(
    tier_id: int, body: StakeTierIn, _admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Changes apply to tables opened from now on; open tables keep their copy."""
    tier = await session.get(StakeTier, tier_id)
    if tier is None:
        raise ApiError(404, "not_found", "Stake level not found.")
    for key, value in body.model_dump().items():
        setattr(tier, key, value)
    try:
        table_svc.validate_tier(tier)
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return _tier_out(tier)


class ScheduledTableIn(BaseModel):
    tier_id: int
    scheduled_start_at: datetime
    title: str | None = Field(default=None, max_length=80)
    # The house tops prizes up to this if entries fall short (paid from promotions).
    guaranteed_prize_cents: int | None = Field(default=None, gt=0)
    # Sign-ups open at this time (default: now); they close when the game starts.
    registration_opens_at: datetime | None = None


@router.post("/tables", status_code=201)
async def schedule_table(
    body: ScheduledTableIn, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Open a table that starts at a set time (needs min_players by then)."""
    tier = await session.get(StakeTier, body.tier_id)
    if tier is None:
        raise ApiError(404, "not_found", "Stake level not found.")
    if body.scheduled_start_at.tzinfo is None or body.scheduled_start_at <= utcnow():
        raise ApiError(422, "bad_time", "Give a future start time with a timezone.")
    opens = body.registration_opens_at
    if opens is not None and (opens.tzinfo is None or opens >= body.scheduled_start_at):
        raise ApiError(422, "bad_time", "Registration must open (with a timezone) before start.")
    table = await table_svc.open_table(
        session, tier, scheduled_start_at=body.scheduled_start_at, created_by=admin.id
    )
    table.title = body.title
    table.config = {
        **table.config,
        "guaranteed_prize_cents": body.guaranteed_prize_cents,
        "registration_opens_at": opens.isoformat() if opens else None,
    }
    await session.commit()
    return await table_svc.table_view(session, table)


@router.post("/tables/{table_id}/cancel")
async def cancel_table(
    table_id: uuid.UUID, _admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    table = await session.scalar(
        select(GameTable).where(GameTable.id == table_id).with_for_update()
    )
    if table is None:
        raise ApiError(404, "not_found", "Table not found.")
    try:
        await table_svc.cancel(session, table, "admin")
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return await table_svc.table_view(session, table)


class SettleIn(BaseModel):
    finishing_order: list[uuid.UUID] = Field(min_length=1, max_length=100)
    note: str = Field(min_length=5, max_length=500)


class VoidIn(BaseModel):
    note: str = Field(min_length=5, max_length=500)


@router.get("/tables/stale")
async def stale_tables(_admin: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    """Running tables with no result for longer than table.running_alert_minutes."""
    minutes = await cfg.get_int(session, "table.running_alert_minutes")
    return [
        await table_svc.table_view(session, t)
        for t in await table_svc.stale_running(session, minutes)
    ]


@router.post("/tables/{table_id}/settle")
async def settle_table(
    table_id: uuid.UUID, body: SettleIn, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Pay out a running table by hand when the game server's result was lost
    (e.g. from the game server's log). Players not listed finish last."""
    log.warning(
        "admin %s settles table %s: %s (%s)", admin.id, table_id, body.finishing_order, body.note
    )
    try:
        table = await table_svc.settle(session, table_id, body.finishing_order)
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return await table_svc.table_view(session, table)


@router.post("/tables/{table_id}/void")
async def void_table(
    table_id: uuid.UUID, body: VoidIn, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """A running table whose result can't be recovered: everyone gets their
    whole entry back and the table is cancelled."""
    log.warning("admin %s voids table %s (%s)", admin.id, table_id, body.note)
    try:
        table = await table_svc.void_running(session, table_id, f"void by admin: {body.note}")
    except table_svc.TableError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return await table_svc.table_view(session, table)


# ----------------------------------------------------------- withdrawals review


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("/withdrawals")
async def list_withdrawals(
    _admin: AdminUser, session: SessionDep, status: str | None = "pending_review"
) -> list[dict[str, Any]]:
    q = (
        select(Withdrawal, User.email, User.username)
        .join(User, User.id == Withdrawal.user_id)
        .order_by(Withdrawal.created_at)
        .limit(200)
    )
    if status:
        q = q.where(Withdrawal.status == status)
    return [
        {**payouts.view(w), "email": email, "username": username}
        for w, email, username in (await session.execute(q)).all()
    ]


async def _review(
    reference: str,
    approve: bool,
    body: ReviewIn,
    admin: User,
    session: SessionDep,
    paystack: PaystackDep,
) -> dict[str, Any]:
    try:
        w = await payouts.review(session, admin, reference, approve=approve, note=body.note)
    except PaymentError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    if w.status == "approved":
        w = await payouts.send(session, paystack, reference)
        await session.commit()
    return payouts.view(w)


@router.post("/withdrawals/{reference}/resolve")
async def resolve_withdrawal(
    reference: str, body: VoidIn, admin: AdminUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    """A withdrawal stuck in approved/processing: ask Paystack, then book it as
    paid or refund the player."""
    log.warning("admin %s resolves withdrawal %s (%s)", admin.id, reference, body.note)
    try:
        w = await payouts.resolve_stuck(session, paystack, admin, reference, body.note)
    except PaymentError as exc:
        await session.rollback()
        raise ApiError(exc.status_code, exc.code, str(exc)) from exc
    await session.commit()
    return payouts.view(w)


@router.post("/withdrawals/{reference}/approve")
async def approve_withdrawal(
    reference: str, body: ReviewIn, admin: AdminUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    return await _review(reference, True, body, admin, session, paystack)


@router.post("/withdrawals/{reference}/reject")
async def reject_withdrawal(
    reference: str, body: ReviewIn, admin: AdminUser, session: SessionDep, paystack: PaystackDep
) -> dict[str, Any]:
    return await _review(reference, False, body, admin, session, paystack)


# ------------------------------------------------------------------- users


class UserStatusIn(BaseModel):
    status: Literal["active", "suspended", "self_excluded"]


@router.get("/users")
async def search_users(_admin: AdminUser, session: SessionDep, q: str = "") -> list[dict[str, Any]]:
    stmt = select(User).order_by(User.created_at.desc()).limit(50)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.like(like), User.username.like(like)))
    users = (await session.scalars(stmt)).all()
    out = []
    for u in users:
        out.append(
            {
                **user_out(u).model_dump(mode="json"),
                "status": u.status,
                "balance_cents": await ledger.balance(session, ledger.user_available(u.id)),
            }
        )
    return out


@router.get("/users/{user_id}")
async def user_detail(user_id: uuid.UUID, _admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    u = await session.get(User, user_id)
    if u is None:
        raise ApiError(404, "not_found", "User not found.")
    entries = (
        await session.execute(
            select(
                JournalTransaction.id,
                JournalTransaction.kind,
                JournalTransaction.memo,
                JournalTransaction.created_at,
                LedgerEntry.amount,
            )
            .join(LedgerEntry, LedgerEntry.transaction_id == JournalTransaction.id)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerAccount.code == ledger.user_available(u.id))
            .order_by(JournalTransaction.id.desc())
            .limit(100)
        )
    ).all()
    deposits = (
        await session.scalars(
            select(Deposit)
            .where(Deposit.beneficiary_id == u.id)
            .order_by(Deposit.created_at.desc())
            .limit(50)
        )
    ).all()
    withdrawals = (
        await session.scalars(
            select(Withdrawal)
            .where(Withdrawal.user_id == u.id)
            .order_by(Withdrawal.created_at.desc())
            .limit(50)
        )
    ).all()
    return {
        "user": {**user_out(u).model_dump(mode="json"), "status": u.status},
        "balance_cents": await ledger.balance(session, ledger.user_available(u.id)),
        "ledger": [
            {
                "transaction_id": e.id,
                "kind": e.kind,
                "memo": e.memo,
                "amount_cents": e.amount,
                "at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "deposits": [deposit_view(d) for d in deposits],
        "withdrawals": [payouts.view(w) for w in withdrawals],
    }


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: uuid.UUID, body: UserStatusIn, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    u = await session.get(User, user_id)
    if u is None:
        raise ApiError(404, "not_found", "User not found.")
    if u.id == admin.id:
        raise ApiError(409, "self_change", "You can't change your own status.")
    u.status = body.status
    if body.status == "self_excluded":
        # Enforced like a player's own exclusion, and never lifted early from here.
        u.excluded_until = datetime(9999, 12, 31, tzinfo=UTC)
        await table_svc.leave_all_open(session, u)
    if body.status != "active":
        await auth_svc.revoke_all_for_user(session, u.id)
    await session.commit()
    return {**user_out(u).model_dump(mode="json"), "status": u.status}


# ----------------------------------------------------------------- reports


@router.get("/reports/liabilities")
async def liabilities(_admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    """What the house owes players right now vs. what it holds (D-012 FX exposure)."""

    async def total(pattern: str) -> int:
        value = await session.scalar(
            select(func.coalesce(func.sum(LedgerAccount.balance), 0)).where(
                LedgerAccount.code.like(pattern)
            )
        )
        return int(value or 0)

    wallets = await total("user:%")
    escrow = await total("table:%")
    pending = await ledger.balance(session, ledger.PAYOUTS_PENDING)
    owed = wallets + escrow + pending
    rate = await cfg.get_decimal(session, "fx.usd_kes_rate")
    clearing = await ledger.balance(session, ledger.PAYSTACK_CLEARING)
    return {
        "player_wallets_cents": wallets,
        "table_escrow_cents": escrow,
        "payouts_pending_cents": pending,
        "total_owed_cents": owed,
        "total_owed_kes_at_rate": int(Decimal(owed) * rate / 100),
        "usd_kes_rate": str(rate),
        "net_received_via_paystack_cents": -clearing,
        "house_fees_cents": await ledger.balance(session, ledger.HOUSE_FEES),
        "tax_excise_cents": await ledger.balance(session, ledger.TAX_EXCISE),
        "tax_withholding_cents": await ledger.balance(session, ledger.TAX_WITHHOLDING),
    }
