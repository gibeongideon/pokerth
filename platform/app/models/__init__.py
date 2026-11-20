"""All ORM models. Importing this package registers every table on Base.metadata
(Alembic autogenerate relies on that)."""

from app.models.auth import MagicLinkToken, RefreshToken
from app.models.config import ConfigAudit, ConfigSetting
from app.models.ledger import JournalTransaction, LedgerAccount, LedgerEntry
from app.models.payments import Deposit, WebhookEvent
from app.models.user import User

__all__ = [
    "ConfigAudit",
    "ConfigSetting",
    "Deposit",
    "JournalTransaction",
    "LedgerAccount",
    "LedgerEntry",
    "MagicLinkToken",
    "RefreshToken",
    "User",
    "WebhookEvent",
]
