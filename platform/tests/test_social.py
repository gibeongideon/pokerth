import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import StakeTier, TableInvite
from app.services import ledger, social
from tests.conftest import FakeMailer, MakeUser, set_setting


@pytest.fixture
async def tier_id(sessions: async_sessionmaker[AsyncSession]) -> int:
    await set_setting(sessions, "real_money_enabled", True)
    async with sessions() as s:
        tier = StakeTier(
            name="Mid",
            buy_in_cents=2_000,
            fee_type="pct",
            fee_value=Decimal("0.5"),
            fee_min_cents=0,
            seats=6,
            min_players=2,
            start_mode="when_full",
            payout_bps=[6500, 3500],
            enabled=True,
            sort_order=0,
        )
        s.add(tier)
        await s.commit()
        return tier.id


async def _player(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, name: str
) -> tuple[uuid.UUID, dict[str, str]]:
    user, headers = await make_user(f"{name}@example.com", username=name)
    async with sessions() as s:
        await ledger.post(
            s,
            idempotency_key=f"fund:{user.id}",
            kind="adjustment",
            legs=[
                ledger.Leg(ledger.user_available(user.id), 10_000),
                ledger.Leg(ledger.DEV_CREDIT, -10_000),
            ],
        )
        await s.commit()
    return user.id, headers


# -------------------------------------------------------------- 5.1 friends


async def test_friend_requests(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    a, ha = await make_user("amy@example.com", username="amy")
    b, hb = await make_user("ben@example.com", username="ben")

    assert (await client.post("/friends/requests", json={"handle": "ben"}, headers=ha)).json()[
        "status"
    ] == "pending"
    inbox = (await client.get("/friends", headers=hb)).json()
    assert [i["username"] for i in inbox["incoming"]] == ["amy"]
    req = inbox["incoming"][0]["request_id"]
    assert (await client.post(f"/friends/requests/{req}/accept", headers=hb)).status_code == 204
    assert [
        f["username"] for f in (await client.get("/friends", headers=ha)).json()["friends"]
    ] == ["ben"]

    # Removing works from either side; a request back the other way auto-accepts.
    assert (await client.delete(f"/friends/{a.id}", headers=hb)).status_code == 204
    assert (await client.get("/friends", headers=ha)).json()["friends"] == []
    await client.post("/friends/requests", json={"handle": "amy"}, headers=hb)
    back = await client.post("/friends/requests", json={"handle": "ben"}, headers=ha)
    assert back.json()["status"] == "accepted"

    # Unknown email does not reveal whether it exists; unknown username is a 404.
    assert (
        await client.post("/friends/requests", json={"handle": "ghost@x.com"}, headers=ha)
    ).json()["status"] == "sent"
    assert (
        await client.post("/friends/requests", json={"handle": "ghost"}, headers=ha)
    ).status_code == 404
    assert b.id


# ---------------------------------------------------- 5.2 personal invites


async def test_personal_invite_accept_and_decline(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    tier_id: int,
) -> None:
    _, host = await _player(sessions, make_user, "host")
    _, pal = await _player(sessions, make_user, "pal")
    _, meh = await _player(sessions, make_user, "meh")
    table = (await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=host)).json()

    # Must be at the table to invite.
    resp = await client.post(
        f"/tables/{table['id']}/invites", json={"handles": ["pal"]}, headers=pal
    )
    assert resp.json()["detail"]["code"] == "not_at_table"

    resp = (
        await client.post(
            f"/tables/{table['id']}/invites",
            json={"handles": ["pal", "meh", "nobody", "host", "PAL"], "message": "Come play!"},
            headers=host,
        )
    ).json()
    assert resp["invited"] == ["pal", "meh"]
    assert {s["handle"]: s["reason"] for s in resp["skipped"]} == {
        "nobody": "not_found",
        "host": "self",
    }
    assert mailer.sent[-1]["subject"] == "You're invited to a Felt Kings table"
    assert 'Felt Kings player "host"' in mailer.sent[-1]["body"]
    assert "$20.00 + $0.10" in mailer.sent[-1]["body"]

    again = (
        await client.post(f"/tables/{table['id']}/invites", json={"handles": ["pal"]}, headers=host)
    ).json()
    assert again["skipped"] == [{"handle": "pal", "reason": "already_invited"}]

    inbox = (await client.get("/invites", headers=pal)).json()
    assert inbox[0]["from"] == "host" and inbox[0]["message"] == "Come play!"
    joined = (await client.post(f"/invites/{inbox[0]['invite_id']}/accept", headers=pal)).json()
    assert joined["players"] == 2 and joined["me"]["status"] == "registered"

    meh_inv = (await client.get("/invites", headers=meh)).json()[0]["invite_id"]
    assert (await client.post(f"/invites/{meh_inv}/decline", headers=meh)).status_code == 204

    rsvp = (await client.get(f"/tables/{table['id']}/invites", headers=host)).json()
    assert {r["invitee"]: r["status"] for r in rsvp} == {"pal": "accepted", "meh": "declined"}


# ----------------------------------------------------- 5.3 organized games


async def test_organized_game_and_cancel(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    tier_id: int,
) -> None:
    org_id, org = await _player(sessions, make_user, "org")
    guest_id, guest = await _player(sessions, make_user, "guest")
    start = (utcnow() + timedelta(days=1)).isoformat()

    made = (
        await client.post(
            "/games/organize",
            json={
                "tier_id": tier_id,
                "title": "Friday night poker",
                "message": "Bring snacks",
                "scheduled_start_at": start,
                "organizer_plays": False,
                "invite": ["guest", "newbie@example.com"],
            },
            headers=org,
        )
    ).json()
    table = made["table"]
    assert table["title"] == "Friday night poker" and table["is_organizer"] is True
    assert table["start_mode"] == "scheduled" and table["players"] == 0
    assert made["invite_link"].endswith(f"/join/{table['invite_code']}")
    assert made["invited"] == ["guest", "newbie@example.com"]
    new_mail = next(m for m in mailer.sent if m["to"] == "newbie@example.com")
    assert "Create your free account" in new_mail["body"]

    inv = (await client.get("/invites", headers=guest)).json()[0]
    assert inv["table"]["title"] == "Friday night poker" and inv["table"]["organizer"] == "org"
    await client.post(f"/invites/{inv['invite_id']}/accept", headers=guest)
    async with sessions() as s:
        assert await ledger.balance(s, ledger.user_available(guest_id)) == 10_000 - 2_010

    # Only the organizer can cancel; everyone is refunded and invites are revoked.
    resp = await client.post(f"/tables/{table['id']}/cancel", headers=guest)
    assert resp.status_code == 404
    cancelled = (await client.post(f"/tables/{table['id']}/cancel", headers=org)).json()
    assert cancelled["status"] == "cancelled"
    async with sessions() as s:
        assert await ledger.balance(s, ledger.user_available(guest_id)) == 10_000
        statuses = set((await s.scalars(select(TableInvite.status))).all())
    assert statuses == {"accepted", "revoked"}
    assert org_id


async def test_organize_rejects_bad_start_time(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    _, org = await _player(sessions, make_user, "early")
    soon = (utcnow() + timedelta(minutes=1)).isoformat()
    resp = await client.post(
        "/games/organize",
        json={"tier_id": tier_id, "title": "Too soon", "scheduled_start_at": soon},
        headers=org,
    )
    assert resp.json()["detail"]["code"] == "bad_time"


# ---------------------------------------------------------- 5.4 invite links


async def test_invite_link_and_email_invite_for_new_account(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    _, org = await _player(sessions, make_user, "linker")
    made = (
        await client.post(
            "/games/organize",
            json={"tier_id": tier_id, "title": "Office game", "invite": ["later@example.com"]},
            headers=org,
        )
    ).json()
    code = made["table"]["invite_code"]

    preview = await client.get(f"/invites/code/{code.lower()}")  # no sign-in needed
    assert preview.status_code == 200
    assert preview.json()["title"] == "Office game" and preview.json()["players"] == 1
    assert (await client.get("/invites/code/NOPE1234")).status_code == 404

    # The invited email signs up later: the invite is waiting for them.
    new_id, new = await _player(sessions, make_user, "later")
    inbox = (await client.get("/invites", headers=new)).json()
    assert [i["table"]["title"] for i in inbox] == ["Office game"]
    joined = await client.post(f"/invites/{inbox[0]['invite_id']}/accept", headers=new)
    assert joined.status_code == 200 and joined.json()["players"] == 2

    # Anyone else with the link joins with the code.
    _, other = await _player(sessions, make_user, "walkin")
    resp = await client.post(
        f"/tables/{made['table']['id']}/join", json={"invite_code": code}, headers=other
    )
    assert resp.status_code == 200 and resp.json()["players"] == 3
    assert new_id


# ------------------------------------------------------- 5.5 expiry + limits


async def test_invite_limits_and_expiry(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    await set_setting(sessions, "invites.per_day", 2)
    _, host = await _player(sessions, make_user, "spammer")
    for name in ("x1", "x2", "x3"):
        await make_user(f"{name}@example.com", username=name)
    table = (await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=host)).json()
    resp = (
        await client.post(
            f"/tables/{table['id']}/invites", json={"handles": ["x1", "x2", "x3"]}, headers=host
        )
    ).json()
    assert resp["invited"] == ["x1", "x2"]
    assert resp["skipped"] == [{"handle": "x3", "reason": "invite_limit"}]

    async with sessions() as s:
        await s.execute(
            update(TableInvite)
            .where(TableInvite.status == "pending")
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
        assert await social.expire_invites(s) == 2
        await s.commit()


async def test_friends_only_setting(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    await set_setting(sessions, "invites.friends_only", True)
    _, host = await _player(sessions, make_user, "picky")
    await make_user("stranger@example.com", username="stranger")
    table = (await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=host)).json()
    resp: Any = (
        await client.post(
            f"/tables/{table['id']}/invites", json={"handles": ["stranger"]}, headers=host
        )
    ).json()
    assert resp["skipped"] == [{"handle": "stranger", "reason": "not_friends"}]


async def test_mail_outage_does_not_break_invites(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    tier_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.mailer import MailError

    async def down(*_a: Any, **_k: Any) -> None:
        raise MailError("ConnectionRefusedError")

    _, org = await _player(sessions, make_user, "mailless")
    await make_user("buddy@example.com", username="buddy")
    monkeypatch.setattr(mailer, "send", down)
    made = await client.post(
        "/games/organize",
        json={"tier_id": tier_id, "title": "No mail tonight", "invite": ["buddy"]},
        headers=org,
    )
    assert made.status_code == 201 and made.json()["invited"] == ["buddy"]
    link = await client.post("/auth/magic-link", json={"email": "someone@example.com"})
    assert link.status_code == 503 and link.json()["detail"]["code"] == "email_unavailable"
