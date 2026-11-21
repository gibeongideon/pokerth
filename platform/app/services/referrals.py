"""Referral codes and bonuses (Phase 5.6)."""

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Friendship, PlayerInvite, Referral, User
from app.services import config_registry as cfg
from app.services import ledger
from app.services.ledger import Leg
from app.services.mailer import Mailer, MailError

log = logging.getLogger(__name__)

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
    """The player's personal invite link: a landing page that signs people up."""
    return f"{get_settings().public_base_url}/i/{code}"


def _name(u: User) -> str:
    return u.display_name or u.username or u.email.split("@")[0]


async def _befriend(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    """Make two players friends (accepted), unless they already have a row."""
    if a == b:
        return
    existing = await session.scalar(
        select(Friendship).where(
            or_(
                (Friendship.requester_id == a) & (Friendship.addressee_id == b),
                (Friendship.requester_id == b) & (Friendship.addressee_id == a),
            )
        )
    )
    if existing is None:
        session.add(
            Friendship(requester_id=a, addressee_id=b, status="accepted", responded_at=utcnow())
        )
    elif existing.status != "accepted":
        existing.status, existing.responded_at = "accepted", utcnow()


async def attach(session: AsyncSession, new_user: User, code: str | None) -> None:
    """A brand-new account: credit and connect whoever invited it.

    - The referral (and any bonus) goes only to the owner of the invite link's
      code the player actually used - never to someone who merely typed their
      email earlier, so nobody can pre-claim strangers.
    - That inviter becomes a friend straight away (`referral.auto_friend`):
      the new player chose their link.
    - Everyone else who invited this email is marked "joined" on their list
      and sends a friend request the new player can accept or ignore.
    """
    referrer: User | None = None
    if code:
        referrer = await session.scalar(
            select(User).where(User.referral_code == code.strip().upper())
        )
    if referrer is not None and referrer.id == new_user.id:
        referrer = None
    invites = (
        await session.scalars(
            select(PlayerInvite)
            .where(PlayerInvite.email == new_user.email)
            .order_by(PlayerInvite.created_at)
        )
    ).all()
    for inv in invites:
        inv.status, inv.joined_user_id, inv.joined_at = "joined", new_user.id, utcnow()
    if referrer is not None:
        session.add(Referral(referrer_id=referrer.id, referred_id=new_user.id, status="pending"))
        if await cfg.get_bool(session, "referral.auto_friend"):
            await _befriend(session, referrer.id, new_user.id)
    for inviter_id in {inv.inviter_id for inv in invites} - ({referrer.id} if referrer else set()):
        await _friend_request(session, inviter_id, new_user.id)
    await session.flush()


async def _friend_request(
    session: AsyncSession, requester: uuid.UUID, addressee: uuid.UUID
) -> None:
    existing = await session.scalar(
        select(Friendship.id).where(
            or_(
                (Friendship.requester_id == requester) & (Friendship.addressee_id == addressee),
                (Friendship.requester_id == addressee) & (Friendship.addressee_id == requester),
            )
        )
    )
    if existing is None:
        session.add(Friendship(requester_id=requester, addressee_id=addressee, status="pending"))


async def inviter_preview(session: AsyncSession, code: str) -> dict[str, Any] | None:
    """Public: who owns this invite code (for the /i/<code> landing page)."""
    u = await session.scalar(select(User).where(User.referral_code == code.strip().upper()))
    if u is None or u.status != "active":
        return None
    return {"code": u.referral_code, "inviter": _name(u), "username": u.username}


@dataclass
class EmailInviteResult:
    invited: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


async def invite_emails(
    session: AsyncSession,
    mailer: Mailer,
    inviter: User,
    emails: list[str],
    message: str | None = None,
) -> EmailInviteResult:
    """Invite people to the platform by email. Existing players get a friend
    request instead of an email; the answer is the same either way."""
    from app.services import social  # local import: social uses this module too

    code = await code_for(session, inviter)
    per_day = await cfg.get_int(session, "invites.per_day")
    sent_today = await session.scalar(
        select(func.count())
        .select_from(PlayerInvite)
        .where(
            PlayerInvite.inviter_id == inviter.id,
            PlayerInvite.sent_at > utcnow() - timedelta(hours=24),
        )
    )
    budget = per_day - (sent_today or 0)
    result = EmailInviteResult()
    to_send: list[str] = []
    for raw in dict.fromkeys(e.strip().lower() for e in emails if e.strip()):
        if raw == inviter.email:
            result.skipped.append({"handle": raw, "reason": "self"})
            continue
        if budget <= 0:
            result.skipped.append({"handle": raw, "reason": "invite_limit"})
            continue
        existing = await session.scalar(select(User).where(User.email == raw))
        if existing is not None:
            # Already plays: a friend request instead of an email. Reported
            # exactly like any other invite, so emails can't be probed.
            if existing.status == "active":
                await social.request_friend(session, inviter, raw)
            budget -= 1
            result.invited.append(raw)
            continue
        inv = await session.scalar(
            select(PlayerInvite).where(
                PlayerInvite.inviter_id == inviter.id, PlayerInvite.email == raw
            )
        )
        if inv is not None and inv.sent_at > utcnow() - timedelta(hours=24):
            result.skipped.append({"handle": raw, "reason": "already_invited"})
            continue
        if inv is None:
            session.add(PlayerInvite(inviter_id=inviter.id, email=raw, status="pending"))
        else:
            inv.sent_at = utcnow()  # a reminder, at most once a day
        budget -= 1
        result.invited.append(raw)
        to_send.append(raw)
    await session.commit()

    note = social.player_note(message)
    name = social.strip_links(_name(inviter))
    for address in to_send:
        try:
            await mailer.send(
                address,
                "You're invited to Felt Kings",
                f'Felt Kings player "{name}" wants you at their poker table.{note}\n\n'
                "Sit & Go poker with friends. Top up with M-Pesa or card, "
                "prizes paid to your wallet.\n\n"
                f"Join with one tap (no password needed):\n{link(code)}\n\n"
                f"18+ only. Ignore this email if you're not interested.",
            )
        except MailError as exc:
            log.warning("player invite email to %s failed: %s", address, exc)
    return result


async def sent_invites(session: AsyncSession, inviter: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(PlayerInvite)
            .where(PlayerInvite.inviter_id == inviter.id)
            .order_by(PlayerInvite.created_at.desc())
            .limit(100)
        )
    ).all()
    names: dict[uuid.UUID, str] = {}
    joined_ids = [r.joined_user_id for r in rows if r.joined_user_id]
    if joined_ids:
        for u in (await session.scalars(select(User).where(User.id.in_(joined_ids)))).all():
            names[u.id] = _name(u)
    return [
        {
            "email": r.email,
            "status": r.status,
            "joined_as": names.get(r.joined_user_id) if r.joined_user_id else None,
            "sent_at": r.sent_at,
        }
        for r in rows
    ]


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
