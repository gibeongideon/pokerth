import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import jobs
from app.models import Deposit, WebhookEvent
from app.services import ledger
from app.services.payments import PaymentError, normalize_ke_phone
from tests.conftest import PAYSTACK_SECRET, FakePaystack, MakeUser, set_setting


@pytest.fixture
async def real_money(sessions: async_sessionmaker[AsyncSession]) -> None:
    await set_setting(sessions, "real_money_enabled", True)


def _signed(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    sig = hmac.new(PAYSTACK_SECRET.encode(), raw, hashlib.sha512).hexdigest()
    return raw, {"x-paystack-signature": sig, "content-type": "application/json"}


async def _webhook(client: httpx.AsyncClient, data: dict[str, Any], event: str = "charge.success"):
    raw, headers = _signed({"event": event, "data": data})
    return await client.post("/webhooks/paystack", content=raw, headers=headers)


async def _balance(client: httpx.AsyncClient, headers: dict[str, str]) -> int:
    return int((await client.get("/wallet", headers=headers)).json()["available_usd_cents"])


# ------------------------------------------------------------------ quotes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0712345678", "+254712345678"),
        ("254712345678", "+254712345678"),
        ("+254 112-345-678", "+254112345678"),
        ("0112345678", "+254112345678"),
    ],
)
def test_phone_normalization(raw: str, expected: str) -> None:
    assert normalize_ke_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "0812345678", "+255712345678", ""])
def test_phone_rejects_non_kenyan_mobile(raw: str) -> None:
    with pytest.raises(PaymentError):
        normalize_ke_phone(raw)


async def test_quote_uses_rate_129_and_rounds_up(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    _, headers = await make_user()
    q = (
        await client.get(
            "/wallet/deposits/quote?channel=mpesa&amount_usd_cents=1000", headers=headers
        )
    ).json()
    assert (q["charge_currency"], q["charge_amount"], q["fx_rate"]) == ("KES", 129000, "129")

    q = (
        await client.get(
            "/wallet/deposits/quote?channel=mpesa&amount_usd_cents=101", headers=headers
        )
    ).json()
    assert q["charge_amount"] == 13100  # 1.01 * 129 = 130.29 -> KES 131

    await set_setting(sessions, "fx.spread_pct", "2")
    q = (
        await client.get(
            "/wallet/deposits/quote?channel=mpesa&amount_usd_cents=1000", headers=headers
        )
    ).json()
    assert q["charge_amount"] == 131600  # 10 * 131.58 = 1315.8 -> KES 1316

    q = (
        await client.get(
            "/wallet/deposits/quote?channel=card&amount_usd_cents=1000", headers=headers
        )
    ).json()
    assert (q["charge_currency"], q["charge_amount"]) == ("USD", 1000)

    bad = await client.get(
        "/wallet/deposits/quote?channel=card&amount_usd_cents=50", headers=headers
    )
    assert bad.status_code == 400


# ------------------------------------------------------------------- gates


async def test_deposit_gates(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], make_user: MakeUser
) -> None:
    _, headers = await make_user()
    body = {"channel": "card", "amount_usd_cents": 1000}
    resp = await client.post("/wallet/deposits", json=body, headers=headers)
    assert resp.json()["detail"]["code"] == "real_money_disabled"

    await set_setting(sessions, "real_money_enabled", True)
    _, no_terms = await make_user(terms=False)
    resp = await client.post("/wallet/deposits", json=body, headers=no_terms)
    assert resp.json()["detail"]["code"] == "terms_required"

    _, no_kyc = await make_user(kyc_tier=0)
    resp = await client.post("/wallet/deposits", json=body, headers=no_kyc)
    assert resp.json()["detail"]["code"] == "kyc_required"


# ------------------------------------------------------- card + webhook


async def test_card_deposit_settles_once_via_webhook(
    client: httpx.AsyncClient, paystack: FakePaystack, make_user: MakeUser, real_money: None
) -> None:
    _, headers = await make_user()
    resp = await client.post(
        "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 2500}, headers=headers
    )
    assert resp.status_code == 201
    dep = resp.json()["deposit"]
    assert dep["status"] == "pending"
    assert resp.json()["next"]["authorization_url"].endswith(dep["reference"])
    _, path, sent = paystack.requests[-1]
    assert path == "/transaction/initialize"
    assert sent and (sent["amount"], sent["currency"], sent["channels"]) == (2500, "USD", ["card"])

    tx = paystack.success(dep)
    assert (await _webhook(client, tx)).status_code == 200
    assert await _balance(client, headers) == 2500

    # Paystack redelivers the same event, and we also poll: still credited once.
    assert (await _webhook(client, tx)).status_code == 200
    paystack.verify_results[dep["reference"]] = tx
    await client.get(f"/wallet/deposits/{dep['reference']}", headers=headers)
    assert await _balance(client, headers) == 2500

    hist = (await client.get("/wallet/history", headers=headers)).json()
    assert [(h["kind"], h["amount_usd_cents"]) for h in hist] == [("deposit", 2500)]


async def test_webhook_rejects_bad_signature(client: httpx.AsyncClient) -> None:
    raw = json.dumps({"event": "charge.success", "data": {"reference": "DEP-X"}}).encode()
    resp = await client.post(
        "/webhooks/paystack", content=raw, headers={"x-paystack-signature": "0" * 128}
    )
    assert resp.status_code == 401
    resp = await client.post("/webhooks/paystack", content=raw)
    assert resp.status_code == 401


@pytest.mark.parametrize("override", [{"amount": 100}, {"currency": "KES"}, {"status": "failed"}])
async def test_webhook_amount_currency_or_status_mismatch_never_credits(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
    override: dict[str, Any],
) -> None:
    _, headers = await make_user()
    dep = (
        await client.post(
            "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 2500}, headers=headers
        )
    ).json()["deposit"]
    assert (await _webhook(client, paystack.success(dep, **override))).status_code == 200
    assert await _balance(client, headers) == 0
    async with sessions() as s:
        status = await s.scalar(select(Deposit.status).where(Deposit.reference == dep["reference"]))
    assert status == ("failed" if override.get("status") else "mismatch")


async def test_webhook_failure_returns_500_and_is_retried(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers = await make_user()
    dep = (
        await client.post(
            "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 1000}, headers=headers
        )
    ).json()["deposit"]
    tx = paystack.success(dep)

    from app.services import payments

    real_settle = payments.settle_deposit

    async def boom(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(payments, "settle_deposit", boom)
    assert (await _webhook(client, tx)).status_code == 500
    async with sessions() as s:
        ev = await s.scalar(select(WebhookEvent))
        assert ev is not None and ev.processed_at is None and "db hiccup" in (ev.last_error or "")

    monkeypatch.setattr(payments, "settle_deposit", real_settle)
    assert (await _webhook(client, tx)).status_code == 200
    assert await _balance(client, headers) == 1000


# ------------------------------------------------------------------ mpesa


async def test_mpesa_deposit_for_a_friend_settles_by_poll(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
) -> None:
    payer, headers = await make_user()
    friend, friend_headers = await make_user(username="friend_1")
    resp = await client.post(
        "/wallet/deposits",
        json={
            "channel": "mpesa",
            "amount_usd_cents": 1000,
            "phone": "0712345678",
            "recipient": "friend_1",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    dep = resp.json()["deposit"]
    assert resp.json()["next"]["type"] == "mpesa_prompt"
    _, path, sent = paystack.requests[-1]
    assert path == "/charge"
    assert sent and sent["mobile_money"] == {"phone": "+254712345678", "provider": "mpesa"}
    assert (sent["amount"], sent["currency"]) == (129000, "KES")

    # Poll before the verify window: no Paystack call yet. Then age the row and poll.
    paystack.verify_results[dep["reference"]] = paystack.success(dep)
    async with sessions() as s:
        await s.execute(update(Deposit).values(created_at=datetime.now(UTC) - timedelta(minutes=1)))
        await s.commit()
    polled = (await client.get(f"/wallet/deposits/{dep['reference']}", headers=headers)).json()
    assert polled["status"] == "success"

    assert await _balance(client, friend_headers) == 1000
    assert await _balance(client, headers) == 0
    assert payer.id != friend.id


async def test_deposit_daily_limit(
    client: httpx.AsyncClient,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
) -> None:
    await set_setting(sessions, "deposit.daily_max_usd_cents", 3000)
    _, headers = await make_user()
    body = {"channel": "card", "amount_usd_cents": 2000}
    assert (await client.post("/wallet/deposits", json=body, headers=headers)).status_code == 201
    resp = await client.post("/wallet/deposits", json=body, headers=headers)
    assert resp.json()["detail"]["code"] == "daily_limit"


async def test_paystack_start_failure_marks_deposit_failed(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
) -> None:
    _, headers = await make_user()
    paystack.fail_next = "Currency not supported by merchant"
    resp = await client.post(
        "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 1000}, headers=headers
    )
    assert resp.status_code == 502
    async with sessions() as s:
        assert await s.scalar(select(Deposit.status)) == "failed"


# --------------------------------------------------------------- transfers


async def test_p2p_transfer(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
) -> None:
    _, a = await make_user(username="alice")
    _, b = await make_user(username="bob_k")
    dep = (
        await client.post(
            "/wallet/deposits", json={"channel": "card", "amount_usd_cents": 5000}, headers=a
        )
    ).json()["deposit"]
    await _webhook(client, paystack.success(dep))

    body = {"recipient": "bob_k", "amount_usd_cents": 1500, "idempotency_key": "tx-0001-abcd"}
    resp = await client.post("/wallet/transfers", json=body, headers=a)
    assert resp.json()["detail"]["code"] == "feature_disabled"

    await set_setting(sessions, "p2p_transfers_enabled", True)
    assert (await client.post("/wallet/transfers", json=body, headers=a)).status_code == 201
    assert (
        await client.post("/wallet/transfers", json=body, headers=a)
    ).status_code == 201  # retry
    assert await _balance(client, a) == 3500
    assert await _balance(client, b) == 1500

    too_much = {**body, "idempotency_key": "tx-0002-abcd", "amount_usd_cents": 10_001}
    assert (await client.post("/wallet/transfers", json=too_much, headers=a)).json()["detail"][
        "code"
    ] == "amount_out_of_range"

    broke = {**body, "recipient": "alice", "idempotency_key": "tx-0003-abcd"}
    resp = await client.post("/wallet/transfers", json=broke, headers=b)
    assert resp.status_code == 201  # bob can send back what he has
    resp = await client.post(
        "/wallet/transfers", json={**broke, "idempotency_key": "tx-0004-abcd"}, headers=b
    )
    assert resp.json()["detail"]["code"] == "insufficient_funds"

    me = await client.post(
        "/wallet/transfers",
        json={**body, "recipient": "alice", "idempotency_key": "tx-5-abcdef"},
        headers=a,
    )
    assert me.json()["detail"]["code"] == "self_transfer"


# -------------------------------------------------------------------- jobs


async def test_expire_and_reconcile_jobs(
    client: httpx.AsyncClient,
    paystack: FakePaystack,
    make_user: MakeUser,
    sessions: async_sessionmaker[AsyncSession],
    real_money: None,
) -> None:
    _, headers = await make_user()
    refs = []
    for _ in range(3):
        dep = (
            await client.post(
                "/wallet/deposits",
                json={"channel": "card", "amount_usd_cents": 1000},
                headers=headers,
            )
        ).json()["deposit"]
        refs.append(dep)
    lost_webhook, abandoned, fresh = refs
    paystack.verify_results[lost_webhook["reference"]] = paystack.success(lost_webhook)

    async with sessions() as s:
        await s.execute(
            update(Deposit)
            .where(Deposit.reference != fresh["reference"])
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    counts = await jobs.expire_stale_deposits(sessions, paystack.client())
    assert counts == {"settled": 1, "closed": 1, "kept": 0}
    assert await _balance(client, headers) == 1000

    # Reconciliation finds a success Paystack has but we never settled.
    paystack.listed = [paystack.success(fresh)]
    report = await jobs.reconcile_deposits(sessions, paystack.client(), datetime.now(UTC))
    assert report["settled_late"] == [fresh["reference"]]
    assert await _balance(client, headers) == 2000

    async with sessions() as s:
        assert await ledger.balance(s, ledger.PAYSTACK_CLEARING) == -2000
        statuses = dict((await s.execute(select(Deposit.reference, Deposit.status))).all())
    assert statuses[abandoned["reference"]] == "expired"
