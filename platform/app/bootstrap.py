"""First-run setup for a server (staging or production).

    python -m app.bootstrap [--admin you@example.com]

Creates the default stake levels if there are none, and marks the given email
as admin (it signs in with a magic link as usual; the account is created if it
doesn't exist yet). No demo players or money - that's app.seed, local only.
Safe to run again.
"""

import argparse
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.security import utcnow
from app.models import StakeTier, User
from app.seed import TIERS
from app.services import tables as table_svc
from app.services.auth import normalize_email


async def main(admin_email: str | None) -> None:
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
            print(f"created {len(TIERS)} stake levels")
        if admin_email:
            email = normalize_email(admin_email)
            user = await s.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, email_verified_at=utcnow())
                s.add(user)
            user.is_admin = True
            print(f"{email} is an admin")
        await table_svc.ensure_open_tables(s)
        await s.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", help="email to make admin")
    asyncio.run(main(parser.parse_args().admin))
