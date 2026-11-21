"""single price labels for open tables

Revision ID: 2fc825f95259
Revises: 8e6ca0d6c458
Create Date: 2026-11-21 16:49:56.908892
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2fc825f95259"
down_revision: str | None = "8e6ca0d6c458"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Tables still taking players: show one price (fees included)."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, config FROM game_tables WHERE status IN ('open', 'ready_check')")
    ).fetchall()
    for table_id, config in rows:
        buy_in = int(config.get("buy_in_cents") or 0)
        if buy_in == 0:
            continue
        fee, excise = int(config.get("fee_cents") or 0), int(config.get("excise_cents") or 0)
        total = buy_in + fee + excise
        detail = f"${buy_in / 100:,.2f} to the prize pool + ${fee / 100:,.2f} entry fee"
        if excise:
            detail += f" + ${excise / 100:,.2f} tax"
        config = {**config, "price_label": f"${total / 100:,.2f}", "price_detail": detail}
        conn.execute(
            sa.text("UPDATE game_tables SET config = CAST(:c AS jsonb) WHERE id = :i"),
            {"c": json.dumps(config), "i": table_id},
        )


def downgrade() -> None:
    pass  # labels only; nothing to undo
