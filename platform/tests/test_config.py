import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ConfigAudit
from tests.conftest import MakeUser


async def test_defaults_and_admin_update_with_audit(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    admin, headers = await make_user(is_admin=True)
    resp = await client.get("/admin/settings", headers=headers)
    assert resp.status_code == 200
    by_key = {s["key"]: s for s in resp.json()}
    assert by_key["fx.usd_kes_rate"]["value"] == "129"
    assert by_key["real_money_enabled"]["value"] is False

    resp = await client.put(
        "/admin/settings/fx.usd_kes_rate", json={"value": "130.5"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "130.5"
    assert resp.json()["overridden"] is True

    wallet = await client.get("/wallet", headers=headers)
    assert wallet.json()["usd_kes_rate"] == "130.5"

    async with sessions() as s:
        audit = (await s.execute(select(ConfigAudit))).scalars().all()
    assert [(a.key, a.old_value, a.new_value, a.actor_id) for a in audit] == [
        ("fx.usd_kes_rate", None, "130.5", admin.id)
    ]


async def test_invalid_values_rejected(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    _, headers = await make_user(is_admin=True)
    for key, value in [
        ("real_money_enabled", "yes"),
        ("fx.usd_kes_rate", "0"),
        ("fx.usd_kes_rate", "abc"),
        ("deposit.min_usd_cents", 1.5),
        ("no.such.setting", 1),
    ]:
        resp = await client.put(f"/admin/settings/{key}", json={"value": value}, headers=headers)
        assert resp.status_code == 422, (key, value)


async def test_non_admin_forbidden(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    _, headers = await make_user()
    assert (await client.get("/admin/settings", headers=headers)).status_code == 403
    assert (await client.get("/admin/settings")).status_code == 401
