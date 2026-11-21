import asyncio
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import jwt
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import utcnow
from app.models import GameTable, StakeTier, TableSeat, User
from app.services import ledger
from app.services import tables as svc
from app.services.game_gateway import LocalGateway, sign_internal
from tests.conftest import MakeUser, set_setting

GW = LocalGateway()


# ---------------------------------------------------------------- helpers


async def _tier(sessions: async_sessionmaker[AsyncSession], **overrides: Any) -> StakeTier:
    values: dict[str, Any] = {
        "name": "High",
        "buy_in_cents": 10_000,
        "fee_type": "pct",
        "fee_value": Decimal("0.5"),
        "fee_min_cents": 0,
        "seats": 3,
        "min_players": 2,
        "start_mode": "when_full",
        "payout_bps": [6500, 3500],
        "enabled": True,
        "sort_order": 0,
    }
    values.update(overrides)
    async with sessions() as s:
        tier = StakeTier(**values)
        svc.validate_tier(tier)
        s.add(tier)
        await s.commit()
        return tier


async def _player(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, name: str, cents: int = 20_000
) -> tuple[User, dict[str, str]]:
    user, headers = await make_user(username=name)
    if cents:
        async with sessions() as s:
            await ledger.post(
                s,
                idempotency_key=f"fund:{user.id}",
                kind="adjustment",
                legs=[
                    ledger.Leg(ledger.user_available(user.id), cents),
                    ledger.Leg(ledger.DEV_CREDIT, -cents),
                ],
            )
            await s.commit()
    return user, headers


async def _bal(sessions: async_sessionmaker[AsyncSession], code: str) -> int:
    async with sessions() as s:
        return await ledger.balance(s, code)


@pytest.fixture
async def real_money(sessions: async_sessionmaker[AsyncSession]) -> None:
    await set_setting(sessions, "real_money_enabled", True)


# ------------------------------------------------------------- pure logic


def test_fee_and_price_label() -> None:
    tier = StakeTier(
        buy_in_cents=10_000,
        fee_type="pct",
        fee_value=Decimal("0.5"),
        fee_min_cents=0,
        fee_max_cents=None,
    )
    assert svc.compute_fee(tier) == 50
    assert svc.Price(10_000, 50, 0).label == "$100.00 + $0.50"
    assert svc.Price(0, 0, 0).label == "Free"
    tier.fee_min_cents = 75
    assert svc.compute_fee(tier) == 75
    tier.fee_type, tier.fee_value, tier.fee_max_cents = "flat", Decimal("300"), 200
    assert svc.compute_fee(tier) == 200


def test_split_prizes() -> None:
    assert svc.split_prizes(30_000, [6500, 3500], 3) == [19_500, 10_500]
    assert svc.split_prizes(10_001, [6500, 3500], 2) == [6501, 3500]  # leftover to 1st
    assert svc.split_prizes(20_000, [5000, 3000, 2000], 2) == [12_500, 7_500]  # rescaled


@pytest.mark.parametrize(
    "bad",
    [
        {"payout_bps": [6000, 3000]},
        {"payout_bps": [3500, 6500]},
        {"seats": 11},
        {"min_players": 4},
        {"payout_bps": [5000, 3000, 2000]},
        {"start_mode": "sometimes"},
    ],
)
def test_validate_tier_rejects(bad: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "name": "x",
        "buy_in_cents": 100,
        "fee_type": "pct",
        "fee_value": Decimal("1"),
        "fee_min_cents": 0,
        "seats": 3,
        "min_players": 2,
        "start_mode": "when_full",
        "payout_bps": [6500, 3500],
    }
    values.update(bad)
    with pytest.raises(svc.TableError):
        svc.validate_tier(StakeTier(**values))


# ------------------------------------------------------------ full lifecycle


async def test_sit_and_go_from_lobby_to_payout(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
) -> None:
    tier = await _tier(sessions)
    players = [await _player(sessions, make_user, n) for n in ("ann", "ben", "cat")]

    tiers = (await client.get("/lobby/tiers")).json()
    assert tiers[0]["price_label"] == "$100.00 + $0.50"
    assert tiers[0]["total_kes_reference"] == 12_965  # 100.50 * 129

    # Three quick-plays fill the 3-seat table; it moves to the ready check.
    views = []
    for _, h in players:
        resp = await client.post("/lobby/quick-play", json={"tier_id": tier.id}, headers=h)
        assert resp.status_code == 200, resp.text
        views.append(resp.json())
    table_id = uuid.UUID(views[0]["id"])
    assert len({v["id"] for v in views}) == 1
    assert views[-1]["status"] == "ready_check"
    for user, _ in players:
        assert await _bal(sessions, ledger.user_available(user.id)) == 20_000 - 10_050
    assert await _bal(sessions, ledger.table_escrow(table_id)) == 30_000
    assert await _bal(sessions, ledger.HOUSE_FEES) == 150

    # A replacement table opened for the lobby.
    lobby = (await client.get(f"/lobby/tables?tier_id={tier.id}")).json()
    assert [t["status"] for t in lobby] == ["ready_check", "open"]

    # Everyone confirms; the game starts and seat tokens can be issued.
    for _, h in players:
        view = (await client.post(f"/tables/{table_id}/ready", headers=h)).json()
    assert view["status"] == "running"
    tok = (await client.get(f"/tables/{table_id}/seat-token", headers=players[0][1])).json()
    pub = (await client.get("/internal/seat-token-key")).text
    claims = jwt.decode(tok["token"], pub, algorithms=["EdDSA"], audience="game-server")
    assert (claims["sub"], claims["tbl"], claims["name"]) == (
        str(players[0][0].id),
        str(table_id),
        "ann",
    )
    assert claims["cfg"] == {
        "players": 3,
        "chips": 3000,
        "sb": 10,
        "blind_minutes": 5,
        "title": "High",
    }

    # Game server reports the result (HMAC-signed): cat wins, ann second.
    order = [players[2][0].id, players[0][0].id, players[1][0].id]
    body = json.dumps(
        {"table_id": str(table_id), "finishing_order": [str(u) for u in order]}
    ).encode()
    bad = await client.post(
        f"/internal/games/{table_id}/result", content=body, headers={"x-signature": "0" * 64}
    )
    assert bad.status_code == 401
    # A correctly signed result for another table can't be replayed here.
    other = json.dumps(
        {"table_id": str(uuid.uuid4()), "finishing_order": [str(u) for u in order]}
    ).encode()
    replay = await client.post(
        f"/internal/games/{table_id}/result",
        content=other,
        headers={"x-signature": sign_internal(other)},
    )
    assert replay.status_code == 422
    ok = await client.post(
        f"/internal/games/{table_id}/result",
        content=body,
        headers={"x-signature": sign_internal(body)},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "finished"
    again = await client.post(
        f"/internal/games/{table_id}/result",
        content=body,
        headers={"x-signature": sign_internal(body)},
    )
    assert again.status_code == 200  # idempotent

    assert await _bal(sessions, ledger.user_available(players[2][0].id)) == 9_950 + 19_500
    assert await _bal(sessions, ledger.user_available(players[0][0].id)) == 9_950 + 10_500
    assert await _bal(sessions, ledger.user_available(players[1][0].id)) == 9_950
    assert await _bal(sessions, ledger.table_escrow(table_id)) == 0

    final = (await client.get(f"/tables/{table_id}", headers=players[2][1])).json()
    assert final["me"]["finish_position"] == 1 and final["me"]["prize_cents"] == 19_500


async def test_withholding_tax_and_excise(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, real_money: None
) -> None:
    await set_setting(sessions, "tax.excise_pct", "10")
    await set_setting(sessions, "tax.withholding_pct", "20")
    tier = await _tier(sessions, seats=2, payout_bps=[10_000])
    a, _ = await _player(sessions, make_user, "taxa")
    b, _ = await _player(sessions, make_user, "taxb")
    async with sessions() as s:
        table = await svc.open_table(s, tier)
        assert table.config["price_label"] == "$100.00 + $0.50 + $10.00 tax"
        for u in (a, b):
            await svc.join(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        for u in (a, b):
            await svc.mark_ready(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        await svc.settle(s, table.id, [a.id, b.id])
        await s.commit()
    assert await _bal(sessions, ledger.TAX_EXCISE) == 2_000
    assert await _bal(sessions, ledger.TAX_WITHHOLDING) == 4_000
    assert await _bal(sessions, ledger.user_available(a.id)) == 20_000 - 11_050 + 16_000


# --------------------------------------------------------------- pulling out


async def test_pull_out_window(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
) -> None:
    tier = await _tier(sessions)
    user, h = await _player(sessions, make_user, "quitter")
    view = (await client.post("/lobby/quick-play", json={"tier_id": tier.id}, headers=h)).json()
    assert view["me"]["can_pull_out"] is True
    left = await client.post(f"/tables/{view['id']}/leave", headers=h)
    assert left.status_code == 200
    assert await _bal(sessions, ledger.user_available(user.id)) == 20_000  # fee refunded too

    # Rejoin, then let the grace window pass: pulling out is refused.
    await client.post(f"/tables/{view['id']}/join", json={}, headers=h)
    async with sessions() as s:
        await s.execute(update(TableSeat).values(joined_at=utcnow() - timedelta(hours=1)))
        await s.commit()
    late = await client.post(f"/tables/{view['id']}/leave", headers=h)
    assert late.json()["detail"]["code"] == "pull_out_closed"
    assert await _bal(sessions, ledger.user_available(user.id)) == 20_000 - 10_050


# ---------------------------------------------------------------- timers


@pytest.mark.parametrize(("policy", "refund"), [("refund", 10_050), ("forfeit_fee", 10_000)])
async def test_ready_check_timeout_removes_no_shows(
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
    policy: str,
    refund: int,
) -> None:
    await set_setting(sessions, "table.no_show_policy", policy)
    tier = await _tier(sessions)
    users = [(await _player(sessions, make_user, f"p{i}{policy[:3]}"))[0] for i in range(3)]
    async with sessions() as s:
        table = await svc.open_table(s, tier)
        for u in users:
            await svc.join(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        await svc.mark_ready(s, GW, table.id, await s.get(User, users[0].id))  # type: ignore[arg-type]
        table.ready_deadline = utcnow() - timedelta(seconds=1)
        await s.commit()
        counts = await svc.tick(s, GW)
        await s.commit()
        await s.refresh(table)
    assert counts["ready_timeouts"] == 1
    assert table.status == "open"  # back to taking players, ann still seated
    assert await _bal(sessions, ledger.user_available(users[1].id)) == 20_000 - 10_050 + refund
    async with sessions() as s:
        statuses = sorted((await s.scalars(select(TableSeat.status))).all())
    assert statuses == ["registered", "removed", "removed"]


async def test_scheduled_table_cancels_and_refunds_when_short(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
) -> None:
    tier = await _tier(sessions, seats=6, min_players=3)
    _, admin = await make_user(is_admin=True)
    start = (utcnow() + timedelta(minutes=5)).isoformat()
    t = (
        await client.post(
            "/admin/tables", json={"tier_id": tier.id, "scheduled_start_at": start}, headers=admin
        )
    ).json()
    assert t["start_mode"] == "scheduled"
    u, h = await _player(sessions, make_user, "early")
    await client.post(f"/tables/{t['id']}/join", json={}, headers=h)

    async with sessions() as s:
        await s.execute(
            update(GameTable)
            .where(GameTable.id == uuid.UUID(t["id"]))
            .values(scheduled_start_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
        await svc.tick(s, GW)
        await s.commit()
        table = await s.get(GameTable, uuid.UUID(t["id"]))
        assert table is not None and table.status == "cancelled"
    assert await _bal(sessions, ledger.user_available(u.id)) == 20_000


async def test_scheduled_table_starts_with_enough_players(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, real_money: None
) -> None:
    tier = await _tier(sessions, seats=6, min_players=2)
    users = [(await _player(sessions, make_user, f"sch{i}"))[0] for i in range(3)]
    async with sessions() as s:
        table = await svc.open_table(s, tier, scheduled_start_at=utcnow() + timedelta(hours=1))
        for u in users:
            await svc.join(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        assert table.status == "open"  # not full-triggered
        table.scheduled_start_at = utcnow() - timedelta(seconds=1)
        await s.commit()
        await svc.tick(s, GW)
        assert table.status == "ready_check"
        for u in users[:2]:
            await svc.mark_ready(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        table.ready_deadline = utcnow() - timedelta(seconds=1)
        await s.commit()
        await svc.tick(s, GW)  # third player no-show: start with the two who are ready
        await s.commit()
        await s.refresh(table)
    assert table.status == "running"


# ------------------------------------------------------------------ guards


async def test_join_guards(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
) -> None:
    tier = await _tier(sessions)
    free = await _tier(sessions, name="Free", buy_in_cents=0, payout_bps=[10_000])
    _, h = await _player(sessions, make_user, "guarded", cents=5_000)

    resp = await client.post("/lobby/quick-play", json={"tier_id": tier.id}, headers=h)
    assert resp.json()["detail"]["code"] == "real_money_disabled"
    ok = await client.post("/lobby/quick-play", json={"tier_id": free.id}, headers=h)
    assert ok.status_code == 200  # free play works without real money

    await set_setting(sessions, "real_money_enabled", True)
    resp = await client.post("/lobby/quick-play", json={"tier_id": tier.id}, headers=h)
    assert resp.json()["detail"]["code"] == "too_many_tables"  # one table at a time (H5)
    await set_setting(sessions, "table.max_concurrent_per_user", 3)
    resp = await client.post("/lobby/quick-play", json={"tier_id": tier.id}, headers=h)
    assert resp.json()["detail"]["code"] == "insufficient_funds"

    _, nameless = await make_user()
    resp = await client.post("/lobby/quick-play", json={"tier_id": free.id}, headers=nameless)
    assert resp.json()["detail"]["code"] == "username_required"


async def test_private_table_needs_code(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
) -> None:
    tier = await _tier(sessions)
    _, host = await _player(sessions, make_user, "host")
    _, guest = await _player(sessions, make_user, "guest")
    t = (await client.post("/tables/private", json={"tier_id": tier.id}, headers=host)).json()
    assert t["invite_code"] and len(t["invite_code"]) == 8
    assert all(x["id"] != t["id"] for x in (await client.get("/lobby/tables")).json())
    no = await client.post(f"/tables/{t['id']}/join", json={}, headers=guest)
    assert no.json()["detail"]["code"] == "invite_required"
    yes = await client.post(
        f"/tables/{t['id']}/join", json={"invite_code": t["invite_code"].lower()}, headers=guest
    )
    assert yes.status_code == 200 and yes.json()["players"] == 2


async def test_concurrent_joins_never_overfill(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, real_money: None
) -> None:
    tier = await _tier(sessions, seats=4, payout_bps=[10_000])
    users = [(await _player(sessions, make_user, f"rush{i}"))[0] for i in range(9)]
    async with sessions() as s:
        table = await svc.open_table(s, tier)
        await s.commit()

    async def attempt(u: User) -> str:
        async with sessions() as s:
            try:
                await svc.join(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
                await s.commit()
                return "ok"
            except svc.TableError as exc:
                await s.rollback()
                return exc.code

    results = await asyncio.gather(*(attempt(u) for u in users))
    assert results.count("ok") == 4
    assert set(results) == {"ok", "table_not_open"}
    assert await _bal(sessions, ledger.table_escrow(table.id)) == 40_000


async def test_admin_stake_levels(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    _, admin = await make_user(is_admin=True)
    body = {
        "name": "Big",
        "buy_in_cents": 50_000,
        "fee_type": "flat",
        "fee_value": "150",
        "seats": 9,
        "min_players": 3,
        "payout_bps": [5000, 3000, 2000],
    }
    created = await client.post("/admin/stake-tiers", json=body, headers=admin)
    assert created.status_code == 201 and created.json()["fee_cents"] == 150
    bad = await client.post(
        "/admin/stake-tiers", json={**body, "payout_bps": [5000, 5001]}, headers=admin
    )
    assert bad.status_code == 422
    tiers = (await client.get("/lobby/tiers")).json()
    assert tiers[-1]["price_label"] == "$500.00 + $1.50"


# ------------------------------------------------------- 5.7 tournaments


async def test_scheduled_tournament_with_guarantee_and_registration_window(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    real_money: None,
) -> None:
    tier = await _tier(sessions, seats=6, min_players=2, payout_bps=[6500, 3500])
    _, admin = await make_user(is_admin=True)
    start = utcnow() + timedelta(hours=2)
    body = {
        "tier_id": tier.id,
        "title": "Sunday $500 guaranteed",
        "scheduled_start_at": start.isoformat(),
        "guaranteed_prize_cents": 50_000,
        "registration_opens_at": (utcnow() + timedelta(hours=1)).isoformat(),
    }
    t = (await client.post("/admin/tables", json=body, headers=admin)).json()
    assert t["prize_pool_cents"] == 50_000 and t["title"] == "Sunday $500 guaranteed"

    a, ha = await _player(sessions, make_user, "early_a")
    b, hb = await _player(sessions, make_user, "early_b")
    resp = await client.post(f"/tables/{t['id']}/join", json={}, headers=ha)
    assert resp.json()["detail"]["code"] == "registration_not_open"

    async with sessions() as s:
        table = await s.get(GameTable, uuid.UUID(t["id"]))
        assert table is not None
        table.config = {**table.config, "registration_opens_at": None}
        await s.commit()
    for h in (ha, hb):
        assert (await client.post(f"/tables/{t['id']}/join", json={}, headers=h)).status_code == 200

    async with sessions() as s:
        table = await s.get(GameTable, uuid.UUID(t["id"]))
        assert table is not None
        table.status = "running"
        for seat in (await s.scalars(select(TableSeat))).all():
            seat.status = "playing"
        await s.commit()
        await svc.settle(s, table.id, [b.id, a.id])
        await s.commit()
    # Only $200 came in; the house topped the pool up to $500.
    assert await _bal(sessions, ledger.user_available(b.id)) == 20_000 - 10_050 + 32_500
    assert await _bal(sessions, ledger.user_available(a.id)) == 20_000 - 10_050 + 17_500
    assert await _bal(sessions, ledger.PROMOTIONS) == -30_000

    bad = await client.post(
        "/admin/tables",
        json={**body, "registration_opens_at": (start + timedelta(hours=1)).isoformat()},
        headers=admin,
    )
    assert bad.status_code == 422


async def test_result_without_no_shows_places_them_last(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, real_money: None
) -> None:
    tier = await _tier(sessions, seats=3, payout_bps=[6500, 3500])
    users = [(await _player(sessions, make_user, f"ns{i}"))[0] for i in range(3)]
    async with sessions() as s:
        table = await svc.open_table(s, tier)
        for u in users:
            await svc.join(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        for u in users:
            await svc.mark_ready(s, GW, table.id, await s.get(User, u.id))  # type: ignore[arg-type]
        # The game server only saw two players; the third never connected.
        await svc.settle(s, table.id, [users[2].id, users[0].id])
        await s.commit()
        places = {
            seat.user_id: (seat.finish_position, seat.prize_cents)
            for seat in (await s.scalars(select(TableSeat))).all()
        }
    assert places[users[2].id] == (1, 19_500)
    assert places[users[0].id] == (2, 10_500)
    assert places[users[1].id] == (3, 0)

    async with sessions() as s:
        with pytest.raises(svc.TableError):
            await svc.settle(s, uuid.uuid4(), [users[0].id])
