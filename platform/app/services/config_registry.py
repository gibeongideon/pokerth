"""Typed business settings that admins can change at runtime.

Every setting is declared here with its type and default; the database only
stores overrides (``config_settings``) and every change is audited
(``config_audit``). Values are cached per process for a few seconds, so a
change reaches all API/worker processes within ``_CACHE_TTL_SECONDS``.
"""

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConfigAudit, ConfigSetting

_CACHE_TTL_SECONDS = 5.0


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: type  # bool | int | Decimal | str
    default: Any
    description: str
    min: int | Decimal | None = None
    max: int | Decimal | None = None


_DEFS = [
    # Feature flags (D-007): real money stays off until the licence is granted.
    SettingDef("real_money_enabled", bool, False, "Allow deposits, staked play and payouts."),
    SettingDef("p2p_transfers_enabled", bool, False, "Allow wallet-to-wallet transfers."),
    SettingDef("deposit_on_behalf_enabled", bool, True, "Allow paying into someone else's wallet."),
    # FX (D-017)
    SettingDef("fx.usd_kes_rate", Decimal, Decimal("129"), "KES per 1 USD.", min=Decimal("1")),
    SettingDef(
        "fx.spread_pct",
        Decimal,
        Decimal("0"),
        "Margin added to M-Pesa conversions, in %.",
        min=Decimal("0"),
        max=Decimal("10"),
    ),
    # Deposits (USD cents)
    SettingDef("deposit.min_usd_cents", int, 100, "Smallest deposit.", min=1),
    SettingDef("deposit.max_usd_cents", int, 100_000, "Largest single deposit.", min=1),
    SettingDef(
        "deposit.daily_max_usd_cents", int, 300_000, "Max deposits per payer per 24h.", min=1
    ),
    SettingDef(
        "deposit.pending_expiry_minutes",
        int,
        30,
        "Pending deposits older than this are checked and closed.",
        min=5,
    ),
    # Wallet-to-wallet transfers (USD cents)
    SettingDef("p2p.max_usd_cents", int, 10_000, "Largest single transfer.", min=1),
    SettingDef("p2p.daily_max_usd_cents", int, 50_000, "Max transfers sent per 24h.", min=1),
    # KYC gates (D-014)
    SettingDef("kyc.deposit_min_tier", int, 1, "KYC tier needed to deposit.", min=0, max=2),
    SettingDef("kyc.p2p_min_tier", int, 1, "KYC tier needed to send transfers.", min=0, max=2),
    # Auth
    SettingDef("auth.magic_link_ttl_seconds", int, 900, "Magic link lifetime.", min=60, max=3600),
    SettingDef(
        "auth.magic_link_per_hour", int, 5, "Magic links per email per hour.", min=1, max=50
    ),
]

REGISTRY: dict[str, SettingDef] = {d.key: d for d in _DEFS}


class SettingError(ValueError):
    pass


def _coerce(d: SettingDef, raw: Any) -> Any:
    """Convert a JSON value (from the DB or an admin request) to the setting's type."""
    try:
        if d.type is bool:
            if not isinstance(raw, bool):
                raise SettingError(f"{d.key} must be true or false")
            value: Any = raw
        elif d.type is int:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise SettingError(f"{d.key} must be an integer")
            value = raw
        elif d.type is Decimal:
            if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                raise SettingError(f'{d.key} must be a decimal string, e.g. "129.5"')
            value = Decimal(str(raw))
            if not value.is_finite():
                raise SettingError(f"{d.key} must be finite")
        else:
            value = str(raw)
    except InvalidOperation as exc:
        raise SettingError(f"{d.key}: invalid decimal") from exc
    if d.min is not None and value < d.min:
        raise SettingError(f"{d.key} must be >= {d.min}")
    if d.max is not None and value > d.max:
        raise SettingError(f"{d.key} must be <= {d.max}")
    return value


def _to_json(d: SettingDef, value: Any) -> Any:
    return str(value) if d.type is Decimal else value


_cache: dict[str, Any] = {}
_cache_loaded_at = 0.0


def clear_cache() -> None:
    global _cache_loaded_at
    _cache.clear()
    _cache_loaded_at = 0.0


async def _overrides(session: AsyncSession) -> dict[str, Any]:
    global _cache_loaded_at
    if time.monotonic() - _cache_loaded_at > _CACHE_TTL_SECONDS:
        rows = (await session.execute(select(ConfigSetting))).scalars().all()
        _cache.clear()
        for row in rows:
            d = REGISTRY.get(row.key)
            if d is not None:
                _cache[row.key] = _coerce(d, row.value)
        _cache_loaded_at = time.monotonic()
    return _cache


async def get(session: AsyncSession, key: str) -> Any:
    d = REGISTRY[key]
    return (await _overrides(session)).get(key, d.default)


async def get_bool(session: AsyncSession, key: str) -> bool:
    return bool(await get(session, key))


async def get_int(session: AsyncSession, key: str) -> int:
    return int(await get(session, key))


async def get_decimal(session: AsyncSession, key: str) -> Decimal:
    return Decimal(await get(session, key))


async def all_settings(session: AsyncSession) -> list[dict[str, Any]]:
    overrides = await _overrides(session)
    return [
        {
            "key": d.key,
            "type": d.type.__name__.lower(),
            "value": _to_json(d, overrides.get(d.key, d.default)),
            "default": _to_json(d, d.default),
            "overridden": d.key in overrides,
            "description": d.description,
        }
        for d in _DEFS
    ]


async def set_value(session: AsyncSession, key: str, raw: Any, actor_id: Any) -> Any:
    """Validate, store and audit a change. Caller commits."""
    d = REGISTRY.get(key)
    if d is None:
        raise SettingError(f"unknown setting {key}")
    value = _coerce(d, raw)
    row = await session.get(ConfigSetting, key, with_for_update=True)
    old = row.value if row else None
    new_json = _to_json(d, value)
    if row is None:
        session.add(ConfigSetting(key=key, value=new_json, updated_by=actor_id))
    else:
        row.value = new_json
        row.updated_by = actor_id
    session.add(ConfigAudit(key=key, old_value=old, new_value=new_json, actor_id=actor_id))
    clear_cache()
    return value
