import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import jobs
from app.core.security import utcnow
from app.models import Withdrawal
from app.services import ledger
from tests.conftest import PAYSTACK_SECRET, FakeMailer, FakePaystack, MakeUser, set_setting

PHONE = "+254712345678"


@pytest.fixture
async def ready(sessions: async_sessionmaker[AsyncSession]) -> None:
    await set_setting(sessions, "real_money_enabled", True)
    await set_setting(sessions, "withdraw.deposit_review_hours", 0)


async def _winner(
    sessions: async_sessionmaker[AsyncSession], make_user: MakeUser, cents: int = 50_000, **kw: Any
) -> tuple[uuid.UUID, dict[str, str]]:
    user, headers = await make_user(phone=PHONE, **kw)
    async with sessions() as s:
        await ledger.post(
            s,
            idempotency_key=f"win:{user.id}",
            kind="adjustment",
            legs=[
                ledger.Leg(ledger.user_available(user.id), cents),
                ledger.Leg(ledger.DEV_CREDIT, -cents),
            ],
        )
        await s.commit()
    return user.id, headers


async def _bal(sessions: async_sessionmaker[AsyncSession], code: str) -> int:
    async with sessions() as s:
        return await ledger.balance(s, code)


async def _dest(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/wallet/payout-destinations", json={"phone": "0712 345 678"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _code(mailer: FakeMailer) -> str:
    return mailer.sent[-1]["subject"].rsplit(" ", 1)[1]


async def _webhook(client: httpx.AsyncClient, event: str, data: dict[str, Any]) -> int:
    raw = json.dumps({"event": event, "data": data}).encode()
    sig = hmac.new(PAYSTACK_SECRET.encode(), raw, hashlib.sha512).hexdigest()
    resp = await client.post(
        "/webhooks/paystack", content=raw, headers={"x-paystack-signature": sig}
    )
    return resp.status_code


# ------------------------------------------------------------------ happy path


async def test_withdraw_to_mpesa_end_to_end(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    paystack: FakePaystack,
    ready: None,
) -> None:
    uid, h = await _winner(sessions, make_user)
    dest = await _dest(client, h)

    q = (await client.get("/wallet/withdrawals/quote?amount_usd_cents=10000", headers=h)).json()
    assert (q["fee_usd_cents"], q["payout_amount"]) == (0, 1_290_000)  # $100 -> KES 12,900

    w = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 10_000},
            headers=h,
        )
    ).json()
    assert w["status"] == "awaiting_confirmation"
    assert await _bal(sessions, ledger.user_available(uid)) == 50_000  # nothing moved yet

    wrong = await client.post(
        f"/wallet/withdrawals/{w['reference']}/confirm",
        json={"code": "000000" if _code(mailer) != "000000" else "111111"},
        headers=h,
    )
    assert wrong.json()["detail"]["code"] == "wrong_code"

    ok = (
        await client.post(
            f"/wallet/withdrawals/{w['reference']}/confirm", json={"code": _code(mailer)}, headers=h
        )
    ).json()
    assert ok["status"] == "processing"
    assert await _bal(sessions, ledger.user_available(uid)) == 40_000
    assert await _bal(sessions, ledger.PAYOUTS_PENDING) == 10_000
    sent = paystack.transfers[w["reference"]]
    assert sent["amount"] == 1_290_000
    rec = next(b for _, p, b in paystack.requests if p == "/transferrecipient")
    assert rec and (rec["account_number"], rec["bank_code"]) == ("0712345678", "MPESA")

    assert await _webhook(client, "transfer.success", sent) == 200
    assert await _webhook(client, "transfer.success", sent) == 200  # redelivery
    assert await _bal(sessions, ledger.PAYOUTS_PENDING) == 0
    assert await _bal(sessions, ledger.PAYSTACK_CLEARING) == 10_000
    listing = (await client.get("/wallet/withdrawals", headers=h)).json()
    assert listing[0]["status"] == "success"


async def test_failed_transfer_refunds(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    paystack: FakePaystack,
    ready: None,
) -> None:
    await set_setting(sessions, "withdraw.require_email_code", False)
    await set_setting(sessions, "withdraw.fee_flat_usd_cents", 50)
    uid, h = await _winner(sessions, make_user)
    dest = await _dest(client, h)
    w = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 2_000},
            headers=h,
        )
    ).json()
    assert w["status"] == "processing" and w["fee_usd_cents"] == 50
    assert await _webhook(client, "transfer.reversed", paystack.transfers[w["reference"]]) == 200
    assert await _bal(sessions, ledger.user_available(uid)) == 50_000  # fee refunded too
    assert await _bal(sessions, ledger.HOUSE_FEES) == 0


# ----------------------------------------------------------------- the rules


async def test_rules(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    ready: None,
) -> None:
    uid, h = await _winner(sessions, make_user, cents=300_000)
    dest = await _dest(client, h)

    async def ask(cents: int) -> Any:
        return await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": cents},
            headers=h,
        )

    assert (await ask(100)).json()["detail"]["code"] == "amount_out_of_range"
    assert (await ask(60_000)).json()["detail"]["code"] == "kyc_required"  # tier 2 above $500

    _, other = await make_user(phone="+254799999999")
    resp = await client.post(
        "/wallet/payout-destinations", json={"phone": "0712345678"}, headers=other
    )
    assert resp.json()["detail"]["code"] == "not_your_phone"

    _, broke = await _winner(sessions, make_user, cents=1_000)
    d2 = await _dest(client, broke)
    resp = await client.post(
        "/wallet/withdrawals", json={"destination_id": d2, "amount_usd_cents": 5_000}, headers=broke
    )
    assert resp.json()["detail"]["code"] == "insufficient_funds"

    await set_setting(sessions, "withdraw.daily_max_usd_cents", 15_000)
    await set_setting(sessions, "withdraw.require_email_code", False)
    assert (await ask(10_000)).status_code == 201
    assert (await ask(10_000)).json()["detail"]["code"] == "daily_limit"

    await set_setting(sessions, "real_money_enabled", False)
    assert (await ask(1_000)).json()["detail"]["code"] == "withdrawals_disabled"
    assert uid


async def test_large_or_recent_deposit_goes_to_review(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    paystack: FakePaystack,
    ready: None,
) -> None:
    await set_setting(sessions, "withdraw.require_email_code", False)
    uid, h = await _winner(sessions, make_user, cents=100_000)
    _, admin = await make_user(is_admin=True)
    dest = await _dest(client, h)

    big = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 30_000},
            headers=h,
        )
    ).json()
    assert big["status"] == "pending_review"
    assert "auto-approve" in big["review_reasons"]
    assert paystack.transfers == {}  # nothing sent yet

    queue = (await client.get("/admin/withdrawals", headers=admin)).json()
    assert [q["reference"] for q in queue] == [big["reference"]]
    approved = (
        await client.post(
            f"/admin/withdrawals/{big['reference']}/approve",
            json={"note": "known winner"},
            headers=admin,
        )
    ).json()
    assert approved["status"] == "processing"

    small = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 5_000},
            headers=h,
        )
    ).json()
    assert small["status"] == "processing"  # under the limit: automatic

    # A third one goes to review, the player cancels it and gets the money back.
    review = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 25_000},
            headers=h,
        )
    ).json()
    before = await _bal(sessions, ledger.user_available(uid))
    cancelled = (
        await client.post(f"/wallet/withdrawals/{review['reference']}/cancel", headers=h)
    ).json()
    assert cancelled["status"] == "cancelled"
    assert await _bal(sessions, ledger.user_available(uid)) == before + 25_000


async def test_code_attempts_and_expiry(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    mailer: FakeMailer,
    paystack: FakePaystack,
    ready: None,
) -> None:
    uid, h = await _winner(sessions, make_user)
    dest = await _dest(client, h)
    body = {"destination_id": dest, "amount_usd_cents": 1_000}

    w = (await client.post("/wallet/withdrawals", json=body, headers=h)).json()
    bad = "000000" if _code(mailer) != "000000" else "111111"
    for _ in range(4):
        await client.post(
            f"/wallet/withdrawals/{w['reference']}/confirm", json={"code": bad}, headers=h
        )
    last = await client.post(
        f"/wallet/withdrawals/{w['reference']}/confirm", json={"code": bad}, headers=h
    )
    assert last.json()["detail"]["code"] == "too_many_attempts"

    w2 = (await client.post("/wallet/withdrawals", json=body, headers=h)).json()
    async with sessions() as s:
        await s.execute(
            update(Withdrawal)
            .where(Withdrawal.reference == w2["reference"])
            .values(otp_expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
    counts = await jobs.process_withdrawals(sessions, paystack.client())
    assert counts["expired"] == 1
    assert await _bal(sessions, ledger.user_available(uid)) == 50_000


async def test_send_retry_and_lost_webhook(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    paystack: FakePaystack,
    ready: None,
) -> None:
    await set_setting(sessions, "withdraw.require_email_code", False)
    uid, h = await _winner(sessions, make_user)
    dest = await _dest(client, h)

    paystack.fail_next = "Insufficient balance"  # recipient creation fails first time
    w = (
        await client.post(
            "/wallet/withdrawals",
            json={"destination_id": dest, "amount_usd_cents": 3_000},
            headers=h,
        )
    ).json()
    assert w["status"] == "approved"  # money held, waiting for a retry

    counts = await jobs.process_withdrawals(sessions, paystack.client())
    assert counts["sent"] == 1

    # Webhook never arrives; Paystack says success when asked later.
    paystack.transfers[w["reference"]]["status"] = "success"
    async with sessions() as s:
        await s.execute(update(Withdrawal).values(sent_at=utcnow() - timedelta(hours=1)))
        await s.commit()
    counts = await jobs.process_withdrawals(sessions, paystack.client())
    assert counts["resolved"] == 1
    assert await _bal(sessions, ledger.PAYOUTS_PENDING) == 0
    assert await _bal(sessions, ledger.user_available(uid)) == 47_000


async def test_admin_users_and_liabilities(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    ready: None,
) -> None:
    uid, h = await _winner(sessions, make_user, username="richie")
    _, admin = await make_user(is_admin=True)
    found = (await client.get("/admin/users?q=rich", headers=admin)).json()
    assert found[0]["balance_cents"] == 50_000
    detail = (await client.get(f"/admin/users/{uid}", headers=admin)).json()
    assert detail["ledger"][0]["amount_cents"] == 50_000

    report = (await client.get("/admin/reports/liabilities", headers=admin)).json()
    assert report["player_wallets_cents"] == 50_000
    assert report["total_owed_kes_at_rate"] == 64_500

    resp = await client.put(
        f"/admin/users/{uid}/status", json={"status": "suspended"}, headers=admin
    )
    assert resp.status_code == 200
    assert (await client.get("/me", headers=h)).status_code == 401
