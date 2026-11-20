from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import RgLimit, StakeTier
from app.services import ledger
from tests.conftest import FakePaystack, MakeUser, set_setting


@pytest.fixture
async def tier_id(sessions: async_sessionmaker[AsyncSession]) -> int:
    await set_setting(sessions, "real_money_enabled", True)
    async with sessions() as s:
        tier = StakeTier(
            name="Low",
            buy_in_cents=500,
            fee_type="flat",
            fee_value=Decimal("0"),
            fee_min_cents=0,
            seats=6,
            min_players=2,
            start_mode="when_full",
            payout_bps=[10_000],
            enabled=True,
            sort_order=0,
        )
        s.add(tier)
        await s.commit()
        return tier.id


async def _funded(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, name: str
) -> dict[str, str]:
    user, headers = await make_user(username=name)
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
    return headers


async def test_deposit_limit_tighten_now_loosen_later(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    paystack: FakePaystack,
    tier_id: int,
) -> None:
    _, h = await make_user()
    out = (
        await client.put(
            "/me/limits",
            json={"kind": "deposit", "period": "day", "amount_cents": 3_000},
            headers=h,
        )
    ).json()
    day = next(x for x in out["limits"] if (x["kind"], x["period"]) == ("deposit", "day"))
    assert day["amount_cents"] == 3_000 and day["pending_amount_cents"] is None

    body = {"channel": "card", "amount_usd_cents": 2_000}
    assert (await client.post("/wallet/deposits", json=body, headers=h)).status_code == 201
    resp = await client.post("/wallet/deposits", json=body, headers=h)
    assert resp.json()["detail"]["code"] == "deposit_limit"

    # Raising the limit waits for the cooling-off period...
    out = (
        await client.put(
            "/me/limits",
            json={"kind": "deposit", "period": "day", "amount_cents": 10_000},
            headers=h,
        )
    ).json()
    day = next(x for x in out["limits"] if (x["kind"], x["period"]) == ("deposit", "day"))
    assert day["amount_cents"] == 3_000 and day["pending_amount_cents"] == 10_000
    assert (await client.post("/wallet/deposits", json=body, headers=h)).json()["detail"][
        "code"
    ] == "deposit_limit"

    # ...and applies once it has passed.
    async with sessions() as s:
        await s.execute(
            update(RgLimit).values(pending_effective_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
    assert (await client.post("/wallet/deposits", json=body, headers=h)).status_code == 201


async def test_loss_limit_blocks_joining(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    h = await _funded(sessions, make_user, "careful")
    await client.put(
        "/me/limits", json={"kind": "loss", "period": "week", "amount_cents": 800}, headers=h
    )
    first = await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=h)
    assert first.status_code == 200
    # Pulling out refunds, so it no longer counts as a loss.
    assert (await client.post(f"/tables/{first.json()['id']}/leave", headers=h)).status_code == 200
    again = await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=h)
    assert again.status_code == 200

    # A second $5 table would make the possible loss $10 > $8.
    async with sessions() as s:
        tier = await s.get(StakeTier, tier_id)
        assert tier is not None
        from app.services import tables as svc

        other = await svc.open_table(s, tier)
        await s.commit()
    resp = await client.post(f"/tables/{other.id}/join", json={}, headers=h)
    assert resp.json()["detail"]["code"] == "loss_limit"


async def test_self_exclusion(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    tier_id: int,
) -> None:
    h = await _funded(sessions, make_user, "breaker")
    table = (await client.post("/lobby/quick-play", json={"tier_id": tier_id}, headers=h)).json()
    assert (await client.get("/wallet", headers=h)).json()["available_usd_cents"] == 9_500

    no = await client.post("/me/self-exclude", json={"period": "7d", "confirm": False}, headers=h)
    assert no.status_code == 422
    done = (
        await client.post("/me/self-exclude", json={"period": "7d", "confirm": True}, headers=h)
    ).json()
    assert done["tables_left"] == 1
    assert (await client.get("/wallet", headers=h)).json()["available_usd_cents"] == 10_000

    resp = await client.post(f"/tables/{table['id']}/join", json={}, headers=h)
    assert resp.json()["detail"]["code"] == "self_excluded"
    resp = await client.post(
        "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 1_000}, headers=h
    )
    assert resp.json()["detail"]["code"] == "self_excluded"

    # Can't be shortened: asking for 24h keeps the 7-day end date.
    short = (
        await client.post("/me/self-exclude", json={"period": "24h", "confirm": True}, headers=h)
    ).json()
    assert short["excluded_until"] == done["excluded_until"]
    assert (await client.get("/me", headers=h)).json()["excluded_until"] is not None


async def test_reality_check(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    _, h = await make_user()
    resp = await client.put("/me/reality-check", json={"minutes": 30}, headers=h)
    assert resp.json()["reality_check_minutes"] == 30
    assert (
        await client.put("/me/reality-check", json={"minutes": 5}, headers=h)
    ).status_code == 422
