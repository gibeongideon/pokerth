"""Referral codes and bonuses (Phase 5.6)."""

import secrets
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Referral, User
from app.services import config_registry as cfg
from app.services import ledger
from app.services.ledger import Leg

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


async def code_for(session: AsyncSession, user: User) -> str:
    """The player's referral code, created on first use. Caller commits."""
    while user.referral_code is None:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        taken = await session.scalar(select(User.id).where(User.referral_code == candidate))
        if taken is None:
            user.referral_code = candidate
    return user.referral_code


def link(code: str) -> str:
    return f"{get_settings().public_base_url}/?ref={code}"


async def attach(session: AsyncSession, new_user: User, code: str | None) -> None:
    """Record who referred a brand-new account. Unknown codes are ignored."""
    if not code:
        return
    referrer = await session.scalar(select(User).where(User.referral_code == code.strip().upper()))
    if referrer is None or referrer.id == new_user.id:
        return
    session.add(Referral(referrer_id=referrer.id, referred_id=new_user.id, status="pending"))
    await session.flush()


async def maybe_reward(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Called when a player finishes a paid game. Pays the bonus once, if
    referrals are on and the referrer is under their cap. Caller commits."""
    ref = await session.scalar(
        select(Referral)
        .where(Referral.referred_id == user_id, Referral.status == "pending")
        .with_for_update()
    )
    if ref is None or not await cfg.get_bool(session, "referrals_enabled"):
        return False
    cap = await cfg.get_int(session, "referral.max_rewards_per_referrer")
    earned = await session.scalar(
        select(func.count())
        .select_from(Referral)
        .where(Referral.referrer_id == ref.referrer_id, Referral.status == "rewarded")
    )
    if (earned or 0) >= cap:
        ref.status = "void"
        return False
    to_referrer = await cfg.get_int(session, "referral.referrer_bonus_usd_cents")
    to_referred = await cfg.get_int(session, "referral.referred_bonus_usd_cents")
    legs = []
    if to_referrer:
        legs.append(Leg(ledger.user_available(ref.referrer_id), to_referrer))
    if to_referred:
        legs.append(Leg(ledger.user_available(ref.referred_id), to_referred))
    if legs:
        legs.append(Leg(ledger.PROMOTIONS, -(to_referrer + to_referred)))
        await ledger.post(
            session,
            idempotency_key=f"referral:{ref.id}",
            kind="bonus",
            legs=legs,
            memo="referral bonus",
            meta={"referral_id": str(ref.id)},
        )
    ref.status, ref.rewarded_at = "rewarded", utcnow()
    ref.referrer_bonus_cents, ref.referred_bonus_cents = to_referrer, to_referred
    return True


async def summary(session: AsyncSession, user: User) -> dict[str, Any]:
    code = await code_for(session, user)
    counts = dict(
        (
            await session.execute(
                select(Referral.status, func.count())
                .where(Referral.referrer_id == user.id)
                .group_by(Referral.status)
            )
        ).all()
    )
    earned = await session.scalar(
        select(func.coalesce(func.sum(Referral.referrer_bonus_cents), 0)).where(
            Referral.referrer_id == user.id, Referral.status == "rewarded"
        )
    )
    return {
        "code": code,
        "link": link(code),
        "enabled": await cfg.get_bool(session, "referrals_enabled"),
        "bonus_usd_cents": await cfg.get_int(session, "referral.referrer_bonus_usd_cents"),
        "friend_bonus_usd_cents": await cfg.get_int(session, "referral.referred_bonus_usd_cents"),
        "signed_up": sum(counts.values()),
        "rewarded": counts.get("rewarded", 0),
        "earned_usd_cents": int(earned or 0),
    }
