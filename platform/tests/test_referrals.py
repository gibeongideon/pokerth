from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import StakeTier, User
from app.services import ledger
from app.services import tables as svc
from app.services.game_gateway import LocalGateway
from tests.conftest import FakeGoogle, FakeMailer, MakeUser, set_setting


async def _sign_up(client: httpx.AsyncClient, mailer: FakeMailer, email: str, ref: str) -> dict:
    await client.post("/auth/magic-link", json={"email": email, "ref": ref})
    resp = await client.post(
        "/auth/magic-link/verify", json={"token": mailer.last_token(), "client": "app"}
    )
    return resp.json()


async def test_referral_bonus_after_first_paid_game(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
) -> None:
    await set_setting(sessions, "real_money_enabled", True)
    await set_setting(sessions, "referrals_enabled", True)
    await set_setting(sessions, "referral.referred_bonus_usd_cents", 200)
    referrer, rh = await make_user("ref@example.com", username="referrer")

    info = (await client.get("/me/referral", headers=rh)).json()
    assert len(info["code"]) == 8 and info["link"].endswith(f"/i/{info['code']}")
    assert info["code"] == (await client.get("/me/referral", headers=rh)).json()["code"]

    new = await _sign_up(client, mailer, "newbie@example.com", info["code"].lower())
    assert (await client.get("/me/referral", headers=rh)).json()["signed_up"] == 1

    # Signing up alone pays nothing; finishing a paid game does.
    async with sessions() as s:
        newbie = await s.get(User, new["user"]["id"])
        assert newbie is not None
        newbie.username, newbie.kyc_tier = "newbie", 1
        newbie.terms_accepted_at = referrer.terms_accepted_at
        other, _ = await make_user(username="rival")
        tier = StakeTier(
            name="Micro",
            buy_in_cents=100,
            fee_type="flat",
            fee_value=Decimal("1"),
            fee_min_cents=0,
            seats=2,
            min_players=2,
            start_mode="when_full",
            payout_bps=[10_000],
            enabled=True,
            sort_order=0,
        )
        s.add(tier)
        for uid in (newbie.id, other.id):
            await ledger.post(
                s,
                idempotency_key=f"f:{uid}",
                kind="adjustment",
                legs=[
                    ledger.Leg(ledger.user_available(uid), 1_000),
                    ledger.Leg(ledger.DEV_CREDIT, -1_000),
                ],
            )
        await s.commit()
        assert await ledger.balance(s, ledger.user_available(referrer.id)) == 0

        gw = LocalGateway()
        table = await svc.open_table(s, tier)
        for u in (newbie, await s.get(User, other.id)):
            assert u is not None
            await svc.join(s, gw, table.id, u)
        for u in (newbie, await s.get(User, other.id)):
            assert u is not None
            await svc.mark_ready(s, gw, table.id, u)
        await svc.settle(s, table.id, [other.id, newbie.id])
        await s.commit()

        assert await ledger.balance(s, ledger.user_available(referrer.id)) == 500
        assert await ledger.balance(s, ledger.user_available(newbie.id)) == 1_000 - 101 + 200
        assert await ledger.balance(s, ledger.PROMOTIONS) == -700

    after = (await client.get("/me/referral", headers=rh)).json()
    assert (after["rewarded"], after["earned_usd_cents"]) == (1, 500)


async def test_referrals_off_and_bad_codes(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    google: FakeGoogle,
) -> None:
    _, rh = await make_user("r2@example.com", username="r2")
    code = (await client.get("/me/referral", headers=rh)).json()["code"]
    assert (await client.get("/me/referral", headers=rh)).json()["enabled"] is False

    await _sign_up(client, mailer, "nobody-ref@example.com", "ZZZZZZZZ")  # unknown: ignored
    google.claims = {"sub": "g-77", "email": "gref@example.com", "email_verified": True}
    await client.post("/auth/google", json={"id_token": "good", "ref": code, "client": "app"})
    assert (await client.get("/me/referral", headers=rh)).json()["signed_up"] == 1


async def _friends(client: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    data = (await client.get("/friends", headers=headers)).json()
    return [f["username"] or f["name"] for f in data["friends"]]


async def test_personal_link_preview_and_signup_makes_friends(
    client: httpx.AsyncClient, make_user: MakeUser, mailer: FakeMailer
) -> None:
    _, ah = await make_user("amina@example.com", username="amina")
    code = (await client.get("/me/referral", headers=ah)).json()["code"]

    preview = (await client.get(f"/invites/personal/{code.lower()}")).json()
    assert preview == {"code": code, "inviter": "amina", "username": "amina"}
    assert (await client.get("/invites/personal/NOPE1234")).status_code == 404

    # The landing page asks for an email; the link brings them back to /i/<code>.
    await client.post(
        "/auth/magic-link", json={"email": "juma@example.com", "ref": code, "next": f"/i/{code}"}
    )
    assert f"next=%2Fi%2F{code}" in mailer.sent[-1]["body"]
    new = await client.post(
        "/auth/magic-link/verify", json={"token": mailer.last_token(), "client": "app"}
    )
    jh = {"Authorization": f"Bearer {new.json()['access_token']}"}
    assert (await client.get("/me/referral", headers=ah)).json()["signed_up"] == 1
    assert len(await _friends(client, ah)) == 1
    assert await _friends(client, jh) == ["amina"]


async def test_magic_link_next_must_be_same_site(client: httpx.AsyncClient) -> None:
    for bad in ("https://evil.example", "//evil.example", "javascript:alert(1)"):
        resp = await client.post("/auth/magic-link", json={"email": "x@example.com", "next": bad})
        assert resp.status_code == 422, bad


async def test_email_invite_is_tracked_by_email(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
) -> None:
    _, ah = await make_user("amina@example.com", username="amina")
    _, bh = await make_user("baraka@example.com", username="baraka")
    await make_user("existing@example.com", username="existing")

    r = (
        await client.post(
            "/me/invites",
            headers=ah,
            json={"emails": ["Wanjiru@Example.com", "existing@example.com", "amina@example.com"]},
        )
    ).json()
    # Same answer for an email that already plays (no probing): it gets a friend request.
    assert r["invited"] == ["wanjiru@example.com", "existing@example.com"]
    assert r["skipped"] == [{"handle": "amina@example.com", "reason": "self"}]
    mail = mailer.sent[-1]
    assert mail["to"] == "wanjiru@example.com" and "/i/" in mail["body"]

    # Same email again within a day: not re-sent.
    again = await client.post("/me/invites", headers=ah, json={"emails": ["wanjiru@example.com"]})
    assert again.json()["skipped"] == [
        {"handle": "wanjiru@example.com", "reason": "already_invited"}
    ]
    # A second player invites the same person too.
    await client.post("/me/invites", headers=bh, json={"emails": ["wanjiru@example.com"]})
    assert (await client.get("/me/invites", headers=ah)).json()[0]["status"] == "pending"

    # Wanjiru signs up later, from the plain sign-in page (no link, no code).
    await client.post("/auth/magic-link", json={"email": "wanjiru@example.com"})
    new = await client.post(
        "/auth/magic-link/verify", json={"token": mailer.last_token(), "client": "app"}
    )
    wh = {"Authorization": f"Bearer {new.json()['access_token']}"}
    # Credited to the first inviter; friends with both.
    # No link used: nobody gets referral credit (no pre-claiming strangers),
    # but both inviters see "joined" and sent friend requests.
    assert (await client.get("/me/referral", headers=ah)).json()["signed_up"] == 0
    assert (await client.get("/me/referral", headers=bh)).json()["signed_up"] == 0
    assert await _friends(client, wh) == []
    incoming = (await client.get("/friends", headers=wh)).json()["incoming"]
    assert sorted(f["username"] for f in incoming) == ["amina", "baraka"]
    sent = (await client.get("/me/invites", headers=ah)).json()
    assert sent[0]["status"] == "joined"


async def test_auto_friend_can_be_turned_off(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
) -> None:
    await set_setting(sessions, "referral.auto_friend", False)
    _, ah = await make_user("amina@example.com", username="amina")
    code = (await client.get("/me/referral", headers=ah)).json()["code"]
    await _sign_up(client, mailer, "juma@example.com", code)
    assert (await client.get("/me/referral", headers=ah)).json()["signed_up"] == 1
    assert await _friends(client, ah) == []
