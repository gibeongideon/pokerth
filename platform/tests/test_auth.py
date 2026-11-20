from datetime import timedelta

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import MagicLinkToken
from tests.conftest import FakeGoogle, FakeMailer, MakeUser, set_setting


async def _sign_in(client: httpx.AsyncClient, mailer: FakeMailer, email: str, kind: str = "web"):
    assert (await client.post("/auth/magic-link", json={"email": email})).status_code == 202
    return await client.post(
        "/auth/magic-link/verify", json={"token": mailer.last_token(), "client": kind}
    )


async def test_magic_link_web_sets_cookies_and_creates_user(
    client: httpx.AsyncClient, mailer: FakeMailer
) -> None:
    resp = await _sign_in(client, mailer, "  New.Player@Example.com ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "new.player@example.com"
    assert body["access_token"] is None and body["refresh_token"] is None
    assert "access_token" in resp.cookies and "refresh_token" in resp.cookies
    assert mailer.sent[-1]["to"] == "new.player@example.com"

    me = await client.get("/me")  # cookie auth
    assert me.status_code == 200
    assert me.json()["email"] == "new.player@example.com"


async def test_magic_link_app_returns_tokens(client: httpx.AsyncClient, mailer: FakeMailer) -> None:
    resp = await _sign_in(client, mailer, "app@example.com", kind="app")
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert "access_token" not in resp.cookies
    client.cookies.clear()
    me = await client.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


async def test_magic_link_single_use_and_expiry(
    client: httpx.AsyncClient, mailer: FakeMailer, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await client.post("/auth/magic-link", json={"email": "once@example.com"})
    token = mailer.last_token()
    assert (await client.post("/auth/magic-link/verify", json={"token": token})).status_code == 200
    again = await client.post("/auth/magic-link/verify", json={"token": token})
    assert again.status_code == 401
    assert again.json()["detail"]["code"] == "invalid_link"

    await client.post("/auth/magic-link", json={"email": "late@example.com"})
    async with sessions() as s:
        await s.execute(
            update(MagicLinkToken)
            .where(MagicLinkToken.email == "late@example.com")
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
    late = await client.post("/auth/magic-link/verify", json={"token": mailer.last_token()})
    assert late.status_code == 401


async def test_magic_link_rate_limited_silently(
    client: httpx.AsyncClient, mailer: FakeMailer, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await set_setting(sessions, "auth.magic_link_per_hour", 2)
    for _ in range(4):
        resp = await client.post("/auth/magic-link", json={"email": "spam@example.com"})
        assert resp.status_code == 202
    assert len(mailer.sent) == 2


async def test_refresh_rotation_and_reuse_revokes_family(
    client: httpx.AsyncClient, mailer: FakeMailer
) -> None:
    first = (await _sign_in(client, mailer, "rot@example.com", kind="app")).json()
    r1 = first["refresh_token"]

    second = await client.post("/auth/refresh", json={"refresh_token": r1, "client": "app"})
    assert second.status_code == 200
    r2 = second.json()["refresh_token"]
    assert r2 != r1

    # Replaying the rotated token looks like theft: it fails and kills r2 too.
    replay = await client.post("/auth/refresh", json={"refresh_token": r1, "client": "app"})
    assert replay.status_code == 401
    after = await client.post("/auth/refresh", json={"refresh_token": r2, "client": "app"})
    assert after.status_code == 401


async def test_logout_all(client: httpx.AsyncClient, mailer: FakeMailer) -> None:
    a = (await _sign_in(client, mailer, "multi@example.com", kind="app")).json()
    b = (await _sign_in(client, mailer, "multi@example.com", kind="app")).json()
    headers = {"Authorization": f"Bearer {a['access_token']}"}
    assert (await client.post("/auth/logout-all", headers=headers)).status_code == 204
    for tok in (a["refresh_token"], b["refresh_token"]):
        resp = await client.post("/auth/refresh", json={"refresh_token": tok, "client": "app"})
        assert resp.status_code == 401


async def test_google_links_existing_account(
    client: httpx.AsyncClient, google: FakeGoogle, make_user: MakeUser
) -> None:
    user, _ = await make_user("linked@example.com")
    google.claims = {"sub": "g-123", "email": "Linked@Example.com", "email_verified": True}
    resp = await client.post("/auth/google", json={"id_token": "good", "client": "app"})
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == str(user.id)

    # Second sign-in finds the user by Google subject even if the email changed.
    google.claims = {"sub": "g-123", "email": "other@example.com", "email_verified": True}
    resp = await client.post("/auth/google", json={"id_token": "good", "client": "app"})
    assert resp.json()["user"]["id"] == str(user.id)


async def test_google_rejects_unverified_and_bad_tokens(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    google.claims = {"sub": "g-9", "email": "x@example.com", "email_verified": False}
    resp = await client.post("/auth/google", json={"id_token": "good"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "email_unverified"
    resp = await client.post("/auth/google", json={"id_token": "forged"})
    assert resp.status_code == 401


async def test_profile_and_terms(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    _, headers = await make_user(terms=False)
    _, other = await make_user(username="taken_name")

    resp = await client.patch(
        "/me", json={"username": "ace_01", "phone": "0712 345 678"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "ace_01"
    assert resp.json()["phone"] == "+254712345678"

    assert (
        await client.patch("/me", json={"username": "taken_name"}, headers=headers)
    ).status_code == 409
    assert (
        await client.patch("/me", json={"username": "Bad Name"}, headers=headers)
    ).status_code == 422

    no = await client.post(
        "/me/accept-terms", json={"confirm_over_18": False, "accept_terms": True}, headers=headers
    )
    assert no.status_code == 422
    yes = await client.post(
        "/me/accept-terms", json={"confirm_over_18": True, "accept_terms": True}, headers=headers
    )
    assert yes.json()["terms_accepted"] is True
    assert other  # silence unused


async def test_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/me")
    assert resp.status_code == 401
    resp = await client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
