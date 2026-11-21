"""Friends, personal invites, organized games and invite links (Phase 5.1-5.5).

All functions expect the caller to commit, except the ones that send email,
which commit before sending so an email never refers to unsaved data.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Friendship, GameTable, StakeTier, TableInvite, TableSeat, User
from app.services import config_registry as cfg
from app.services import rg
from app.services import tables as table_svc
from app.services.game_gateway import GameGateway
from app.services.mailer import Mailer, MailError

log = logging.getLogger(__name__)


class SocialError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _name(u: User) -> str:
    return u.display_name or u.username or u.email.split("@")[0]


async def _find(session: AsyncSession, handle: str) -> User | None:
    handle = handle.strip().lower()
    column = User.email if "@" in handle else User.username
    user = await session.scalar(select(User).where(column == handle))
    return user if user is not None and user.status == "active" else None


# ------------------------------------------------------------------ friends


async def _pair(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> list[Friendship]:
    return list(
        (
            await session.scalars(
                select(Friendship).where(
                    or_(
                        and_(Friendship.requester_id == a, Friendship.addressee_id == b),
                        and_(Friendship.requester_id == b, Friendship.addressee_id == a),
                    )
                )
            )
        ).all()
    )


async def are_friends(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    return any(f.status == "accepted" for f in await _pair(session, a, b))


async def request_friend(session: AsyncSession, user: User, handle: str) -> str:
    """Returns the resulting status: 'pending', 'accepted' or 'sent'.
    Unknown emails answer 'sent' too, so emails can't be probed."""
    by_email = "@" in handle
    other = await _find(session, handle)
    if other is None:
        if by_email:
            return "sent"
        raise SocialError("not_found", "No player with that username.", 404)
    if other.id == user.id:
        raise SocialError("self", "You can't add yourself.")
    if by_email:
        # Same answer whether or not the email has an account (no probing).
        await _request(session, user, other)
        return "sent"
    return await _request(session, user, other)


async def _request(session: AsyncSession, user: User, other: User) -> str:

    rows = await _pair(session, user.id, other.id)
    if any(r.status == "accepted" for r in rows):
        return "accepted"
    incoming = next((r for r in rows if r.requester_id == other.id), None)
    if incoming is not None and incoming.status == "pending":
        incoming.status, incoming.responded_at = "accepted", utcnow()
        return "accepted"

    limit = await cfg.get_int(session, "friends.max")
    count = await session.scalar(
        select(func.count())
        .select_from(Friendship)
        .where(Friendship.status == "accepted")
        .where(or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id))
    )
    if (count or 0) >= limit:
        raise SocialError("too_many_friends", f"You can have at most {limit} friends.", 409)

    mine = next((r for r in rows if r.requester_id == user.id), None)
    if mine is None:
        session.add(Friendship(requester_id=user.id, addressee_id=other.id, status="pending"))
    else:
        mine.status, mine.responded_at = "pending", None
    return "pending"


async def respond_friend(
    session: AsyncSession, user: User, request_id: uuid.UUID, accept: bool
) -> None:
    row = await session.get(Friendship, request_id)
    if row is None or row.addressee_id != user.id or row.status != "pending":
        raise SocialError("not_found", "Friend request not found.", 404)
    row.status = "accepted" if accept else "declined"
    row.responded_at = utcnow()


async def remove_friend(session: AsyncSession, user: User, friend_id: uuid.UUID) -> None:
    await session.execute(
        delete(Friendship).where(
            or_(
                and_(Friendship.requester_id == user.id, Friendship.addressee_id == friend_id),
                and_(Friendship.requester_id == friend_id, Friendship.addressee_id == user.id),
            )
        )
    )


async def friends_overview(session: AsyncSession, user: User) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Friendship, User)
            .join(
                User,
                User.id
                == func.coalesce(
                    func.nullif(Friendship.requester_id, user.id), Friendship.addressee_id
                ),
            )
            .where(or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id))
            .where(Friendship.status.in_(("pending", "accepted")))
            .order_by(User.username)
        )
    ).all()
    out: dict[str, Any] = {"friends": [], "incoming": [], "outgoing": []}
    for f, other in rows:
        item = {"user_id": str(other.id), "username": other.username, "name": _name(other)}
        if f.status == "accepted":
            out["friends"].append(item)
        elif f.addressee_id == user.id:
            out["incoming"].append({**item, "request_id": str(f.id)})
        else:
            out["outgoing"].append({**item, "request_id": str(f.id)})
    return out


# ------------------------------------------------------------------ invites


@dataclass
class InviteResult:
    invited: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def join_link(table: GameTable, ref: str | None = None) -> str:
    """Table link; `ref` (the inviter's code) credits a newcomer who signs up from it."""
    base = get_settings().public_base_url
    url = f"{base}/join/{table.invite_code}" if table.invite_code else f"{base}/tables/{table.id}"
    return f"{url}?ref={ref}" if ref else url


async def _can_invite(session: AsyncSession, user: User, table: GameTable) -> None:
    if table.status != "open":
        raise SocialError("table_not_open", "This table is no longer taking players.", 409)
    if table.created_by == user.id:
        return
    seated = await session.scalar(
        select(TableSeat.id).where(
            TableSeat.table_id == table.id,
            TableSeat.user_id == user.id,
            TableSeat.status == "registered",
        )
    )
    if seated is None:
        raise SocialError("not_at_table", "Join the table before inviting friends.", 403)


async def invite(
    session: AsyncSession,
    mailer: Mailer,
    inviter: User,
    table_id: uuid.UUID,
    handles: list[str],
    message: str | None = None,
) -> InviteResult:
    """Invite players (by username or email) to a table. Each handle is reported
    as invited or skipped with a reason; one bad handle doesn't fail the rest."""
    table = await session.get(GameTable, table_id)
    if table is None:
        raise SocialError("not_found", "Table not found.", 404)
    await _can_invite(session, inviter, table)

    per_day = await cfg.get_int(session, "invites.per_day")
    sent_today = await session.scalar(
        select(func.count())
        .select_from(TableInvite)
        .where(TableInvite.inviter_id == inviter.id)
        .where(TableInvite.created_at > utcnow() - timedelta(hours=24))
    )
    per_table = await cfg.get_int(session, "invites.max_per_table")
    sent_table = await session.scalar(
        select(func.count()).select_from(TableInvite).where(TableInvite.table_id == table.id)
    )
    budget = min(per_day - (sent_today or 0), per_table - (sent_table or 0))
    friends_only = await cfg.get_bool(session, "invites.friends_only")
    ttl = timedelta(hours=await cfg.get_int(session, "invites.ttl_hours"))

    result = InviteResult()
    emails: list[tuple[str, User | None]] = []
    for raw in dict.fromkeys(h.strip().lower() for h in handles if h.strip()):
        if budget <= 0:
            result.skipped.append({"handle": raw, "reason": "invite_limit"})
            continue
        by_email = "@" in raw
        target = await _find(session, raw)
        if target is None and not by_email:
            result.skipped.append({"handle": raw, "reason": "not_found"})
            continue
        if target is not None:
            if target.id == inviter.id:
                result.skipped.append({"handle": raw, "reason": "self"})
                continue
            if friends_only and not await are_friends(session, inviter.id, target.id):
                if by_email:  # don't reveal that the email has an account
                    result.invited.append(raw)
                    continue
                result.skipped.append({"handle": raw, "reason": "not_friends"})
                continue
            seated = await session.scalar(
                select(TableSeat.id).where(
                    TableSeat.table_id == table.id,
                    TableSeat.user_id == target.id,
                    TableSeat.status.in_(table_svc.ACTIVE_SEAT),
                )
            )
            if seated is not None:
                if by_email:
                    result.invited.append(raw)
                    continue
                result.skipped.append({"handle": raw, "reason": "already_seated"})
                continue
        who = (
            TableInvite.invitee_id == target.id
            if target is not None
            else TableInvite.invitee_email == raw
        )
        pending = await session.scalar(
            select(TableInvite.id).where(
                TableInvite.table_id == table.id, TableInvite.status == "pending", who
            )
        )
        if pending is not None:
            result.skipped.append({"handle": raw, "reason": "already_invited"})
            continue
        session.add(
            TableInvite(
                table_id=table.id,
                inviter_id=inviter.id,
                invitee_id=target.id if target else None,
                invitee_email=None if target else raw,
                message=(message or "").strip()[:500] or None,
                status="pending",
                expires_at=utcnow() + ttl,
            )
        )
        budget -= 1
        result.invited.append(raw)
        # No gambling invites to people who paused play (in-app invite still shows).
        if target is None or not rg.is_excluded(target):
            emails.append((target.email if target else raw, target))

    from app.services import referrals  # local import: referrals uses this module too

    ref = await referrals.code_for(session, inviter)
    await session.commit()
    for address, target in emails:
        try:
            await mailer.send(
                address, *_invite_email(inviter, table, message, has_account=bool(target), ref=ref)
            )
        except MailError as exc:
            # The in-app invite is saved; a mail outage shouldn't fail the request.
            log.warning("invite email to %s failed: %s", address, exc)
    return result


_URL = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w-]+(\.[\w-]+)*\.(com|net|org|io|co|ke|app|xyz|info|link|me)\b\S*)",
    re.I,
)


def strip_links(text: str) -> str:
    return _URL.sub("[link removed]", text)


def player_note(message: str | None) -> str:
    """A player's personal message, quoted and marked as theirs, with links
    removed (invite emails must not become a phishing channel)."""
    text = _URL.sub("[link removed]", (message or "").strip())[:300]
    return f'\n\nTheir message (written by the player, not by Draely):\n"{text}"' if text else ""


def _invite_email(
    inviter: User, table: GameTable, message: str | None, has_account: bool, ref: str | None = None
) -> tuple[str, str]:
    c = table.config
    what = strip_links(table.title or f"a {c['name']} game")
    when = (
        f"Starts {table.scheduled_start_at:%a %d %b, %H:%M} UTC."
        if table.scheduled_start_at
        else "Starts as soon as the table is full."
    )
    note = player_note(message)
    step = "Tap to join:" if has_account else "Create your free account and join:"
    body = (
        f'Draely player "{strip_links(_name(inviter))}" invited you to {what}.\n\n'
        f"Price: {c['price_label']} · {c['seats']} seats. {when}{note}\n\n"
        f"{step}\n{join_link(table, None if has_account else ref)}\n\n"
        "Ignore this email if you're not interested."
    )
    return "You're invited to a Draely table", body


async def my_invites(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    now = utcnow()
    rows = (
        await session.execute(
            select(TableInvite, GameTable, User)
            .join(GameTable, GameTable.id == TableInvite.table_id)
            .join(User, User.id == TableInvite.inviter_id)
            .where(or_(TableInvite.invitee_id == user.id, TableInvite.invitee_email == user.email))
            .where(TableInvite.status == "pending", TableInvite.expires_at > now)
            .where(GameTable.status == "open")
            .order_by(TableInvite.created_at.desc())
        )
    ).all()
    return [
        {
            "invite_id": str(inv.id),
            "from": inviter.username,
            "message": inv.message,
            "expires_at": inv.expires_at.isoformat(),
            "table": await preview(session, table),
        }
        for inv, table, inviter in rows
    ]


async def _my_pending_invite(
    session: AsyncSession, user: User, invite_id: uuid.UUID
) -> TableInvite:
    inv = await session.scalar(
        select(TableInvite).where(TableInvite.id == invite_id).with_for_update()
    )
    mine = inv is not None and (inv.invitee_id == user.id or inv.invitee_email == user.email)
    if inv is None or not mine:
        raise SocialError("not_found", "Invite not found.", 404)
    if inv.status != "pending" or inv.expires_at <= utcnow():
        raise SocialError("invite_closed", "This invite is no longer open.", 409)
    return inv


async def accept_invite(
    session: AsyncSession, gateway: GameGateway, user: User, invite_id: uuid.UUID
) -> uuid.UUID:
    """Join the table (paying the buy-in like any join). Returns the table id."""
    inv = await _my_pending_invite(session, user, invite_id)
    table = await session.get(GameTable, inv.table_id)
    assert table is not None
    await table_svc.join(session, gateway, table.id, user, table.invite_code)
    inv.status, inv.responded_at = "accepted", utcnow()
    inv.invitee_id = user.id
    return table.id


async def decline_invite(session: AsyncSession, user: User, invite_id: uuid.UUID) -> None:
    inv = await _my_pending_invite(session, user, invite_id)
    inv.status, inv.responded_at = "declined", utcnow()
    inv.invitee_id = user.id


async def table_invites(
    session: AsyncSession, user: User, table_id: uuid.UUID
) -> list[dict[str, Any]]:
    """RSVP list for the organizer or anyone seated at the table."""
    table = await session.get(GameTable, table_id)
    if table is None:
        raise SocialError("not_found", "Table not found.", 404)
    seated = await session.scalar(
        select(TableSeat.id).where(TableSeat.table_id == table.id, TableSeat.user_id == user.id)
    )
    if table.created_by != user.id and seated is None:
        raise SocialError("forbidden", "Only the organizer and players can see invites.", 403)
    rows = (
        await session.execute(
            select(TableInvite, User.username)
            .outerjoin(User, User.id == TableInvite.invitee_id)
            .where(TableInvite.table_id == table.id)
            .order_by(TableInvite.created_at)
        )
    ).all()

    def shown(i: TableInvite, username: str | None) -> str:
        if username:
            return username
        email = i.invitee_email or ""
        # Email addresses are personal: only the inviter and the organizer see them.
        if user.id in (i.inviter_id, table.created_by):
            return email
        name, _, domain = email.partition("@")
        return f"{name[:1]}•••@{domain}" if domain else "invited player"

    return [
        {
            "invite_id": str(i.id),
            "invitee": shown(i, username),
            "status": i.status,
            "responded_at": i.responded_at.isoformat() if i.responded_at else None,
        }
        for i, username in rows
    ]


async def expire_invites(session: AsyncSession) -> int:
    """Close invites whose time is up or whose table is no longer open."""
    closed = select(GameTable.id).where(GameTable.status != "open")
    result = await session.execute(
        update(TableInvite)
        .where(TableInvite.status == "pending")
        .where(or_(TableInvite.expires_at <= utcnow(), TableInvite.table_id.in_(closed)))
        .values(status="expired")
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ----------------------------------------------------------- organized games


async def organize(
    session: AsyncSession,
    gateway: GameGateway,
    mailer: Mailer,
    organizer: User,
    *,
    tier_id: int,
    title: str,
    message: str | None,
    scheduled_start_at: datetime | None,
    organizer_plays: bool,
    invitees: list[str],
    public: bool = False,
    seats: int | None = None,
    hand_help: bool = True,
) -> tuple[GameTable, InviteResult]:
    tier = await session.get(StakeTier, tier_id)
    if tier is None or not tier.enabled:
        raise SocialError("not_found", "That stake level is not available.", 404)
    if scheduled_start_at is not None and (
        scheduled_start_at.tzinfo is None or scheduled_start_at <= utcnow() + timedelta(minutes=5)
    ):
        raise SocialError("bad_time", "Pick a start time at least 5 minutes from now.", 422)
    if not organizer.username:
        raise SocialError("username_required", "Choose a username first.", 403)
    try:
        await table_svc.check_user_can_create(session, tier)
        table = await table_svc.open_table(
            session,
            tier,
            private=not public,
            scheduled_start_at=scheduled_start_at,
            created_by=organizer.id,
        )
        table_svc.set_seats(table, seats)
        table_svc.set_hand_help(table, hand_help)
        # Public tables are shown to everyone: no links in their texts.
        table.title = strip_links(title.strip())[:80] if public else title.strip()[:80]
        msg = (message or "").strip()[:500] or None
        table.message = strip_links(msg) if (public and msg) else msg
        if organizer_plays:
            await table_svc.join(session, gateway, table.id, organizer, table.invite_code)
    except table_svc.TableError as exc:
        raise SocialError(exc.code, str(exc), exc.status_code) from exc
    await session.commit()
    result = (
        await invite(session, mailer, organizer, table.id, invitees, message)
        if invitees
        else InviteResult()
    )
    return table, result


async def organizer_cancel(session: AsyncSession, user: User, table_id: uuid.UUID) -> GameTable:
    table = await session.scalar(
        select(GameTable).where(GameTable.id == table_id).with_for_update()
    )
    if table is None or table.created_by != user.id:
        raise SocialError("not_found", "You didn't organize this table.", 404)
    try:
        await table_svc.cancel(session, table, "organizer")
    except table_svc.TableError as exc:
        raise SocialError(exc.code, str(exc), exc.status_code) from exc
    await session.execute(
        update(TableInvite)
        .where(TableInvite.table_id == table.id, TableInvite.status == "pending")
        .values(status="revoked")
    )
    return table


# -------------------------------------------------------------- invite links


async def preview(session: AsyncSession, table: GameTable) -> dict[str, Any]:
    """What anyone with the link may see, signed in or not."""
    organizer = await session.get(User, table.created_by) if table.created_by else None
    players = await session.scalar(
        select(func.count())
        .select_from(TableSeat)
        .where(TableSeat.table_id == table.id, TableSeat.status.in_(table_svc.ACTIVE_SEAT))
    )
    c = table.config
    return {
        "table_id": str(table.id),
        "title": table.title or c["name"],
        "message": table.message,
        "organizer": organizer.username if organizer else None,
        # Credits the organizer when a newcomer signs up from a shared link.
        "organizer_ref": organizer.referral_code if organizer else None,
        "price_label": c["price_label"],
        "seats_total": c["seats"],
        "players": players or 0,
        "status": table.status,
        "scheduled_start_at": table.scheduled_start_at.isoformat()
        if table.scheduled_start_at
        else None,
        "is_private": table.is_private,
    }


async def preview_by_code(session: AsyncSession, code: str) -> dict[str, Any]:
    table = await session.scalar(
        select(GameTable).where(GameTable.invite_code == code.strip().upper())
    )
    if table is None:
        raise SocialError("not_found", "This invite link is not valid.", 404)
    return await preview(session, table)
