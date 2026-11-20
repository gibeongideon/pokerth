"""Paystack webhook.

1. Reject unless the HMAC-SHA512 signature (and source IP, if configured) match.
2. Store the event under a unique key; a redelivered, already-processed event
   is acknowledged without doing anything.
3. Process. On failure keep the error on the row and answer 500 so Paystack
   retries (dafeapp answered 200 and lost failures).
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import utcnow
from app.models import WebhookEvent
from app.services import payments as pay
from app.services.paystack import verify_signature

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _event_key(event: str, data: dict[str, Any]) -> str:
    ident = data.get("id") or data.get("reference") or data.get("transfer_code") or "?"
    return f"{event}:{ident}"[:160]


async def _process(session: SessionDep, event: str, data: dict[str, Any]) -> None:
    reference = str(data.get("reference") or "")
    if event == "charge.success" and reference.startswith(pay.DEPOSIT_PREFIX):
        await pay.settle_deposit(session, reference, data)
    # Transfer (payout) events arrive in Phase 4.


@router.post("/paystack")
async def paystack_webhook(request: Request, session: SessionDep) -> Response:
    settings = get_settings()
    allowed_ips = settings.paystack_webhook_ips
    if allowed_ips and (request.client is None or request.client.host not in allowed_ips):
        raise ApiError(403, "forbidden", "Source not allowed.")

    raw = await request.body()
    secret = settings.paystack_secret_key.get_secret_value()
    if not verify_signature(secret, raw, request.headers.get("x-paystack-signature")):
        raise ApiError(401, "bad_signature", "Invalid signature.")

    try:
        payload = json.loads(raw)
        event = str(payload["event"])
        data = payload.get("data") or {}
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError(400, "bad_payload", "Malformed payload.") from exc

    key = _event_key(event, data)
    await session.execute(
        insert(WebhookEvent)
        .values(provider="paystack", event_key=key, event=event, payload=payload)
        .on_conflict_do_nothing(index_elements=["provider", "event_key"])
    )
    await session.commit()  # the event is kept even if processing fails below
    row = await session.scalar(
        select(WebhookEvent)
        .where(WebhookEvent.provider == "paystack", WebhookEvent.event_key == key)
        .with_for_update()
    )
    assert row is not None
    if row.processed_at is not None:
        await session.commit()
        return Response(status_code=200)

    try:
        await _process(session, event, data)
        row.attempts += 1
        row.processed_at = utcnow()
        row.last_error = None
        await session.commit()
    except Exception as exc:
        log.exception("paystack webhook %s failed", key)
        await session.rollback()
        # Record the failure in a fresh transaction, then ask Paystack to retry.
        failed = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider == "paystack", WebhookEvent.event_key == key
            )
        )
        if failed is not None:
            failed.attempts += 1
            failed.last_error = f"{exc.__class__.__name__}: {exc}"[:2000]
            await session.commit()
        return Response(status_code=500)
    return Response(status_code=200)
