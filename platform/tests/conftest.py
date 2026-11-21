"""Test fixtures.

Database tests need Postgres + Redis and run only with PLATFORM_TEST_SERVICES=1.
They use a separate ``<db>_test`` database (created on demand) whose tables
are truncated before each test, so the dev database is never touched.
"""

import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

# Tests run in local mode. Set before importing the app: importing app.main
# builds the settings, and outside local they demand production secrets.
os.environ["PLATFORM_ENV"] = "local"
os.environ["PLATFORM_ENABLE_DEV_ROUTES"] = "true"

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.auth import get_google_verifier
from app.core import config
from app.core.db import Base, get_session
from app.core.security import create_access_token, utcnow
from app.main import create_app
from app.models import User
from app.services import config_registry
from app.services.paystack import PaystackClient, get_paystack

SERVICES = os.environ.get("PLATFORM_TEST_SERVICES") == "1"
needs_services = pytest.mark.skipif(
    not SERVICES, reason="set PLATFORM_TEST_SERVICES=1 with Postgres and Redis running"
)

PAYSTACK_SECRET = "sk_test_dummy_secret_for_tests"


# ------------------------------------------------------------------ fakes


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

    def last_token(self) -> str:
        m = re.search(r"token=([A-Za-z0-9_\-]+)", self.sent[-1]["body"])
        assert m, "no token in email"
        return m.group(1)


class FakePaystack:
    """Paystack API double behind httpx.MockTransport, so the real client code runs."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.verify_results: dict[str, dict[str, Any]] = {}
        self.listed: list[dict[str, Any]] = []
        self.fail_next: str | None = None
        self.transfer_status = "pending"  # what POST /transfer answers
        self.transfers: dict[str, dict[str, Any]] = {}  # reference -> transfer

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if self.fail_next:
            msg, self.fail_next = self.fail_next, None
            return httpx.Response(400, json={"status": False, "message": msg})
        path = request.url.path
        if path == "/transaction/initialize":
            assert body is not None
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "authorization_url": f"https://checkout.paystack.com/{body['reference']}",
                        "access_code": "ac_test",
                        "reference": body["reference"],
                    },
                },
            )
        if path == "/charge":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "status": "pay_offline",
                        "display_text": "Please complete on your phone",
                    },
                },
            )
        if path.startswith("/transaction/verify/"):
            ref = path.rsplit("/", 1)[1]
            if ref in self.verify_results:
                return httpx.Response(200, json={"status": True, "data": self.verify_results[ref]})
            return httpx.Response(
                400, json={"status": False, "message": "Transaction reference not found"}
            )
        if path == "/transferrecipient":
            return httpx.Response(
                200, json={"status": True, "data": {"recipient_code": "RCP_test"}}
            )
        if path == "/transfer":
            assert body is not None
            if body["reference"] in self.transfers:
                return httpx.Response(400, json={"status": False, "message": "Duplicate reference"})
            t = {
                "reference": body["reference"],
                "amount": body["amount"],
                "transfer_code": f"TRF_{len(self.transfers)}",
                "status": self.transfer_status,
            }
            self.transfers[body["reference"]] = t
            return httpx.Response(200, json={"status": True, "data": t})
        if path.startswith("/transfer/verify/"):
            ref = path.rsplit("/", 1)[1]
            if ref in self.transfers:
                return httpx.Response(200, json={"status": True, "data": self.transfers[ref]})
            return httpx.Response(404, json={"status": False, "message": "Transfer not found"})
        if path == "/transaction":
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": self.listed,
                    "meta": {"pageCount": 1},
                },
            )
        return httpx.Response(404, json={"status": False, "message": "not mocked"})

    def client(self) -> PaystackClient:
        return PaystackClient(config.get_settings(), transport=httpx.MockTransport(self.handler))

    def success(self, deposit: dict[str, Any], **overrides: Any) -> dict[str, Any]:
        """A Paystack transaction payload that matches ``deposit`` exactly."""
        tx = {
            "id": 1000 + len(self.verify_results),
            "reference": deposit["reference"],
            "status": "success",
            "amount": deposit["charge_amount"],
            "currency": deposit["charge_currency"],
            "gateway_response": "Approved",
        }
        tx.update(overrides)
        return tx


class FakeGoogle:
    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}

    def verify(self, id_token: str) -> dict[str, Any]:
        from app.services.auth import AuthError

        if id_token != "good":
            raise AuthError("invalid_google_token", "Google sign-in failed.")
        return self.claims


# --------------------------------------------------------------- database

_schema_ready = False


def _test_db_url() -> str:
    url = make_url(config.get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


async def _prepare_schema(url: str) -> None:
    global _schema_ready
    if _schema_ready:
        return
    admin_url = make_url(url).set(database="postgres")
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        name = make_url(url).database
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _schema_ready = True


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_PAYSTACK_SECRET_KEY", PAYSTACK_SECRET)
    monkeypatch.setenv("PLATFORM_ENV", "local")
    monkeypatch.setenv("PLATFORM_ENABLE_DEV_ROUTES", "true")
    config.get_settings.cache_clear()
    config_registry.clear_cache()


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not SERVICES:
        pytest.skip("set PLATFORM_TEST_SERVICES=1 with Postgres and Redis running")
    url = _test_db_url()
    await _prepare_schema(url)
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def paystack() -> FakePaystack:
    return FakePaystack()


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
async def client(
    sessions: async_sessionmaker[AsyncSession],
    mailer: FakeMailer,
    paystack: FakePaystack,
    google: FakeGoogle,
) -> AsyncIterator[httpx.AsyncClient]:
    from app.services.mailer import get_mailer

    application = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with sessions() as s:
            yield s

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_mailer] = lambda: mailer
    application.dependency_overrides[get_paystack] = paystack.client
    application.dependency_overrides[get_google_verifier] = lambda: google
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------- helpers

MakeUser = Callable[..., Any]


@pytest.fixture
def make_user(sessions: async_sessionmaker[AsyncSession]) -> MakeUser:
    """Create a user directly in the DB; returns (user, auth headers)."""

    async def _make(
        email: str | None = None,
        *,
        username: str | None = None,
        kyc_tier: int = 1,
        terms: bool = True,
        is_admin: bool = False,
        phone: str | None = None,
    ) -> tuple[User, dict[str, str]]:
        async with sessions() as s:
            user = User(
                email=email or f"u{uuid.uuid4().hex[:8]}@example.com",
                username=username,
                kyc_tier=kyc_tier,
                terms_accepted_at=utcnow() if terms else None,
                is_admin=is_admin,
                phone=phone,
                email_verified_at=utcnow(),
            )
            s.add(user)
            await s.commit()
        return user, {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return _make


async def set_setting(sessions: async_sessionmaker[AsyncSession], key: str, value: Any) -> None:
    async with sessions() as s:
        await config_registry.set_value(s, key, value, None)
        await s.commit()
    config_registry.clear_cache()
