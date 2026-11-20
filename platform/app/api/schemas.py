import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import User


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None
    display_name: str | None
    phone: str | None
    kyc_tier: int
    is_admin: bool
    terms_accepted: bool
    created_at: datetime | None


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        username=u.username,
        display_name=u.display_name,
        phone=u.phone,
        kyc_tier=u.kyc_tier,
        is_admin=u.is_admin,
        terms_accepted=u.terms_accepted_at is not None,
        created_at=u.created_at,
    )
