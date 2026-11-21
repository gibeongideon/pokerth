"""Seed a local database with stake levels and demo players.

    python -m app.seed

Local only: refuses to run unless PLATFORM_ENV=local. Safe to run twice.
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import utcnow
from app.models import StakeTier, User
from app.services import config_registry as cfg
from app.services import ledger
from app.services import tables as table_svc

TIERS = [
    # name, buy-in cents, seats, payout bps
    ("Free play", 0, 6, [10_000]),
    ("Starter", 10, 6, [6500, 3500]),  # small cent stakes: $0.10 and $0.50
    ("Small", 50, 6, [6500, 3500]),
    ("Micro", 100, 6, [6500, 3500]),
    ("Low", 500, 6, [6500, 3500]),
    ("Mid", 2000, 6, [6500, 3500]),
    ("High", 10_000, 6, [6500, 3500]),
]
PLAYERS = ["alice", "bob", "carol", "dave", "erin", "frank", "grace"]
STARTING_BALANCE = 50_000  # $500 each


async def main() -> None:
    if get_settings().env != "local":
        raise SystemExit("seed is for PLATFORM_ENV=local only")
    async with get_sessionmaker()() as s:
        if not (await s.scalars(select(StakeTier))).first():
            for order, (name, buy_in, seats, bps) in enumerate(TIERS):
                tier = StakeTier(
                    name=name,
                    buy_in_cents=buy_in,
                    fee_type="pct",
                    fee_value=Decimal("0.5"),
                    fee_min_cents=1 if buy_in else 0,
                    seats=seats,
                    min_players=2,
                    start_mode="when_full",
                    payout_bps=bps,
                    starting_chips=3000,
                    first_small_blind=10,
                    blind_level_minutes=5,
                    enabled=True,
                    sort_order=order,
                )
                table_svc.validate_tier(tier)
                s.add(tier)

        for name in ["admin", *PLAYERS]:
            email = f"{name}@example.com"
            user = await s.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    username=name,
                    kyc_tier=1,
                    is_admin=name == "admin",
                    email_verified_at=utcnow(),
                    terms_accepted_at=utcnow(),
                )
                s.add(user)
                await s.flush()
            if name != "admin":
                await ledger.post(
                    s,
                    idempotency_key=f"seed:{user.id}",
                    kind="adjustment",
                    legs=[
                        ledger.Leg(ledger.user_available(user.id), STARTING_BALANCE),
                        ledger.Leg(ledger.DEV_CREDIT, -STARTING_BALANCE),
                    ],
                    memo="local demo balance",
                )

        if not await cfg.get_bool(s, "real_money_enabled"):
            await cfg.set_value(s, "real_money_enabled", True, None)
        await s.commit()
        opened = await table_svc.ensure_open_tables(s)
        await s.commit()
    print(f"seeded: {len(TIERS)} stake levels, {len(PLAYERS)} players with $500, {opened} tables")
    print("dashboard: http://localhost:8000/dev/dashboard")


if __name__ == "__main__":
    asyncio.run(main())
