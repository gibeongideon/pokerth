from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.core.security import InvalidTokenError, decode_access_token
from app.models import User
from app.services.mailer import Mailer, get_mailer
from app.services.paystack import PaystackClient, get_paystack

SessionDep = Annotated[AsyncSession, Depends(get_session)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]
PaystackDep = Annotated[PaystackClient, Depends(get_paystack)]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def _bearer_or_cookie(request: Request) -> str | None:
    """Mobile apps send a bearer token; the web app relies on the cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(ACCESS_COOKIE)


async def get_current_user(request: Request, session: SessionDep) -> User:
    token = _bearer_or_cookie(request)
    if not token:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise ApiError(401, "invalid_token", "Your session has expired.") from exc
    user = await session.get(User, user_id)
    if user is None or user.status == "suspended":
        raise ApiError(401, "invalid_token", "Your session has expired.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise ApiError(403, "forbidden", "Admins only.")
    return user


AdminUser = Annotated[User, Depends(get_admin)]
