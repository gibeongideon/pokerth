"""Async Paystack client, ported from dafeapp/subscriptions/paystack.py (D-006)
with the gaps fixed: timeouts on every call, non-JSON responses handled,
empty secret refused, constant-time signature check."""

import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class PaystackError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PaystackDisabledError(PaystackError):
    pass


def verify_signature(secret: str, raw_body: bytes, signature: str | None) -> bool:
    """X-Paystack-Signature = hex HMAC-SHA512 of the raw body with the secret key."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


class PaystackClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._secret = settings.paystack_secret_key.get_secret_value()
        self._base_url = settings.paystack_base_url
        self._timeout = settings.paystack_timeout_seconds
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self._secret)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise PaystackDisabledError("Paystack is not configured")
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._secret}"},
        ) as client:
            try:
                resp = await client.request(method, path, json=json, params=params)
            except httpx.HTTPError as exc:
                raise PaystackError(f"network error: {exc.__class__.__name__}") from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise PaystackError(
                f"non-JSON response ({resp.status_code})", resp.status_code
            ) from exc
        if not isinstance(body, dict) or not body.get("status"):
            message = (
                body.get("message", "request failed") if isinstance(body, dict) else "bad body"
            )
            raise PaystackError(str(message), resp.status_code)
        return body

    async def initialize_transaction(
        self,
        *,
        email: str,
        amount: int,
        currency: str,
        reference: str,
        callback_url: str,
        channels: list[str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        body = await self._request(
            "POST",
            "/transaction/initialize",
            json={
                "email": email,
                "amount": amount,
                "currency": currency,
                "reference": reference,
                "callback_url": callback_url,
                "channels": channels,
                "metadata": metadata,
            },
        )
        data: dict[str, Any] = body["data"]
        return data

    async def charge_mpesa(
        self,
        *,
        email: str,
        amount: int,
        phone: str,
        reference: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Starts an M-Pesa STK push. Result arrives by webhook / verify."""
        body = await self._request(
            "POST",
            "/charge",
            json={
                "email": email,
                "amount": amount,
                "currency": "KES",
                "reference": reference,
                "mobile_money": {"phone": phone, "provider": "mpesa"},
                "metadata": metadata,
            },
        )
        data: dict[str, Any] = body["data"]
        return data

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        body = await self._request("GET", f"/transaction/verify/{reference}")
        data: dict[str, Any] = body["data"]
        return data

    async def list_transactions(
        self,
        *,
        from_iso: str,
        to_iso: str,
        page: int,
        per_page: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """Returns (transactions, page_count)."""
        body = await self._request(
            "GET",
            "/transaction",
            params={
                "from": from_iso,
                "to": to_iso,
                "page": page,
                "perPage": per_page,
            },
        )
        meta = body.get("meta") or {}
        return list(body.get("data") or []), int(meta.get("pageCount") or 1)

    async def create_mpesa_recipient(self, *, name: str, phone: str) -> str:
        """Returns the recipient_code for an M-Pesa number (KES)."""
        body = await self._request(
            "POST",
            "/transferrecipient",
            json={
                "type": "mobile_money",
                "name": name,
                "account_number": phone,
                "bank_code": "MPESA",
                "currency": "KES",
            },
        )
        return str(body["data"]["recipient_code"])

    async def initiate_transfer(
        self, *, amount: int, recipient: str, reference: str, reason: str
    ) -> dict[str, Any]:
        body = await self._request(
            "POST",
            "/transfer",
            json={
                "source": "balance",
                "amount": amount,
                "currency": "KES",
                "recipient": recipient,
                "reference": reference,
                "reason": reason,
            },
        )
        data: dict[str, Any] = body["data"]
        return data

    async def verify_transfer(self, reference: str) -> dict[str, Any]:
        body = await self._request("GET", f"/transfer/verify/{reference}")
        data: dict[str, Any] = body["data"]
        return data


def get_paystack() -> PaystackClient:
    return PaystackClient(get_settings())
