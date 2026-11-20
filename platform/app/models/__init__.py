"""All ORM models. Importing this package registers every table on Base.metadata
(Alembic autogenerate relies on that)."""

from app.models.auth import MagicLinkToken, RefreshToken
from app.models.config import ConfigAudit, ConfigSetting
from app.models.ledger import JournalTransaction, LedgerAccount, LedgerEntry
from app.models.payments import Deposit, WebhookEvent
from app.models.payouts import PayoutDestination, Withdrawal
from app.models.referrals import Referral
from app.models.social import Friendship, TableInvite
from app.models.tables import GameTable, StakeTier, TableSeat
from app.models.user import User

__all__ = [
    "ConfigAudit",
    "ConfigSetting",
    "Deposit",
    "Friendship",
    "GameTable",
    "JournalTransaction",
    "LedgerAccount",
    "LedgerEntry",
    "MagicLinkToken",
    "PayoutDestination",
    "Referral",
    "RefreshToken",
    "StakeTier",
    "TableInvite",
    "TableSeat",
    "User",
    "WebhookEvent",
    "Withdrawal",
]
