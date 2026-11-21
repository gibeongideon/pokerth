"""Passwordless sign-in (D-005): email magic links and Google ID tokens.

Sessions = short-lived JWT access token + opaque refresh token. Refresh tokens
rotate on every use; reuse of an already-rotated token is treated as theft and
revokes the whole token family.
"""

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_token, new_opaque_token, utcnow
from app.models import MagicLinkToken, RefreshToken, User
from app.services import config_registry as cfg
from app.services import referrals
from app.services.mailer import Mailer


class AuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IssuedSession:
    user: User
    access_token: str
    refresh_token: str
    refresh_expires_in: int  # seconds


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ---------------------------------------------------------------- magic links


async def request_magic_link(
    session: AsyncSession,
    mailer: Mailer,
    email: str,
    ip: str | None,
    ref: str | None = None,
    next_path: str | None = None,
) -> None:
    """Create and email a sign-in link. Silently does nothing when rate limited,
    so callers can always answer 202 without revealing anything."""
    email = normalize_email(email)
    # Serialize requests per email so a burst can't slip past the hourly limit.
    await session.execute(select(func.pg_advisory_xact_lock(7_234_003, func.hashtext(email))))
    hour_ago = utcnow() - timedelta(hours=1)
    per_hour = await cfg.get_int(session, "auth.magic_link_per_hour")
    recent = await session.scalar(
        select(func.count())
        .select_from(MagicLinkToken)
        .where(MagicLinkToken.email == email)
        .where(MagicLinkToken.created_at > hour_ago)
    )
    if (recent or 0) >= per_hour:
        return
    if ip:
        per_ip = await cfg.get_int(session, "auth.magic_link_per_ip_hour")
        from_ip = await session.scalar(
            select(func.count())
            .select_from(MagicLinkToken)
            .where(MagicLinkToken.requester_ip == ip)
            .where(MagicLinkToken.created_at > hour_ago)
        )
        if (from_ip or 0) >= per_ip:
            return
    # Only the newest link/code works: older unused ones are retired.
    await session.execute(
        update(MagicLinkToken)
        .where(MagicLinkToken.email == email, MagicLinkToken.used_at.is_(None))
        .values(used_at=utcnow())
    )

    ttl = await cfg.get_int(session, "auth.magic_link_ttl_seconds")
    token = new_opaque_token()
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        MagicLinkToken(
            email=email,
            token_hash=hash_token(token),
            code_hash=_code_hash(email, code),
            expires_at=utcnow() + timedelta(seconds=ttl),
            requester_ip=ip,
            ref_code=(ref or "").strip().upper()[:16] or None,
        )
    )
    await session.commit()

    # `next` brings the player back to where they started (an invite, a table)
    # even when they open the email on another device. Only same-site paths.
    params = {"token": token}
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        params["next"] = next_path
    link = f"{get_settings().public_base_url}/auth/callback?{urlencode(params)}"
    await mailer.send(
        email,
        "Your sign-in link",
        f"Tap the link below to sign in. It works once and expires in {ttl // 60} minutes.\n\n"
        f"{link}\n\n"
        f"In the Draely app? Enter this code instead: {code[:3]} {code[3:]}\n\n"
        "If you didn't ask for this, ignore this email.",
    )


def _code_hash(email: str, code: str) -> str:
    # Keyed with the server secret: a leaked table can't be brute-forced offline.
    return hash_token(f"{get_settings().jwt_secret.get_secret_value()}:{email}:{code}")


MAX_CODE_ATTEMPTS = 5


async def verify_magic_code(session: AsyncSession, email: str, code: str) -> User:
    """Sign in with the 6-digit code from the newest unused link for this email.
    Five wrong codes burn that link. Caller commits."""
    email = normalize_email(email)
    row = await session.scalar(
        select(MagicLinkToken)
        .where(MagicLinkToken.email == email, MagicLinkToken.used_at.is_(None))
        .where(MagicLinkToken.expires_at > utcnow(), MagicLinkToken.code_hash.is_not(None))
        .order_by(MagicLinkToken.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    digits = "".join(ch for ch in code if ch.isdigit())
    # A daily cap on wrong codes per email (across all links) stops guessing
    # by asking for new codes again and again.
    failures = await session.scalar(
        select(func.coalesce(func.sum(MagicLinkToken.code_attempts), 0))
        .where(MagicLinkToken.email == email)
        .where(MagicLinkToken.created_at > utcnow() - timedelta(hours=24))
    )
    if int(failures or 0) >= await cfg.get_int(session, "auth.code_max_failures_per_day"):
        raise AuthError(
            "invalid_code", "Too many wrong codes today. Use the link in the email instead."
        )
    if row is None:
        raise AuthError("invalid_code", "That code is invalid or has expired. Ask for a new email.")
    if not hmac.compare_digest(row.code_hash or "", _code_hash(email, digits)):
        row.code_attempts += 1
        if row.code_attempts >= MAX_CODE_ATTEMPTS:
            row.used_at = utcnow()
        raise AuthError("invalid_code", "That code is invalid or has expired. Ask for a new email.")
    return await _consume(session, row)


async def verify_magic_link(session: AsyncSession, token: str) -> User:
    """Consume a magic link and return the (possibly new) user. Caller commits."""
    row = await session.scalar(
        select(MagicLinkToken)
        .where(MagicLinkToken.token_hash == hash_token(token))
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise AuthError("invalid_link", "This sign-in link is invalid or has expired.")
    return await _consume(session, row)


async def _consume(session: AsyncSession, row: MagicLinkToken) -> User:
    row.used_at = utcnow()

    user = await session.scalar(select(User).where(User.email == row.email))
    if user is None:
        user = User(email=row.email, email_verified_at=utcnow())
        session.add(user)
        await session.flush()
        await referrals.attach(session, user, row.ref_code)
    elif user.email_verified_at is None:
        user.email_verified_at = utcnow()
    _ensure_active(user)
    return user


# --------------------------------------------------------------------- google


class GoogleVerifier(Protocol):
    def verify(self, id_token: str) -> dict[str, Any]: ...


class JwksGoogleVerifier:
    """Checks a Google ID token's signature against Google's published keys."""

    _ISSUERS = ("https://accounts.google.com", "accounts.google.com")

    def __init__(self, client_ids: list[str]) -> None:
        self._client_ids = client_ids
        self._jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", cache_keys=True)

    def verify(self, id_token: str) -> dict[str, Any]:
        if not self._client_ids:
            raise AuthError("google_disabled", "Google sign-in is not configured.")
        try:
            key = self._jwks.get_signing_key_from_jwt(id_token)
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key.key,
                algorithms=["RS256"],
                audience=self._client_ids,
                options={"require": ["sub", "email", "exp", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("invalid_google_token", "Google sign-in failed.") from exc
        if claims.get("iss") not in self._ISSUERS:
            raise AuthError("invalid_google_token", "Google sign-in failed.")
        return claims


async def sign_in_with_google(
    session: AsyncSession, claims: dict[str, Any], ref: str | None = None
) -> User:
    """Find or create the user for verified Google claims. Caller commits."""
    if not claims.get("email_verified"):
        raise AuthError("email_unverified", "Your Google email address is not verified.")
    sub = str(claims["sub"])
    email = normalize_email(str(claims["email"]))

    user = await session.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, email_verified_at=utcnow(), google_sub=sub)
            session.add(user)
            await session.flush()
            await referrals.attach(session, user, ref)
        else:
            # Google verified this email, so linking to the existing account is safe.
            user.google_sub = sub
            user.email_verified_at = user.email_verified_at or utcnow()
    _ensure_active(user)
    return user


# ------------------------------------------------------------------- sessions


def _ensure_active(user: User) -> None:
    if user.status == "suspended":
        raise AuthError("account_suspended", "This account is suspended.")


async def issue_session(
    session: AsyncSession,
    user: User,
    user_agent: str | None,
    family_id: uuid.UUID | None = None,
) -> IssuedSession:
    """Create a refresh token row and an access token. Caller commits."""
    ttl = timedelta(days=get_settings().refresh_token_ttl_days)
    refresh = new_opaque_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(refresh),
            expires_at=utcnow() + ttl,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    await session.flush()
    return IssuedSession(
        user=user,
        access_token=create_access_token(user.id),
        refresh_token=refresh,
        refresh_expires_in=int(ttl.total_seconds()),
    )


async def rotate_refresh_token(
    session: AsyncSession, refresh_token: str, user_agent: str | None
) -> IssuedSession:
    """Exchange a refresh token for a new pair. Caller commits (also on error,
    so that a reuse-triggered family revocation is saved)."""
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    if row is None:
        raise AuthError("invalid_session", "Please sign in again.")
    if row.revoked_at is not None:
        await revoke_family(session, row.family_id)
        raise AuthError("invalid_session", "Please sign in again.")
    if row.expires_at <= utcnow():
        raise AuthError("invalid_session", "Please sign in again.")

    user = await session.get(User, row.user_id)
    if user is None:
        raise AuthError("invalid_session", "Please sign in again.")
    _ensure_active(user)
    row.revoked_at = utcnow()
    return await issue_session(session, user, user_agent, family_id=row.family_id)


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke_token(session: AsyncSession, refresh_token: str) -> None:
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
    )
    if row is not None:
        await revoke_family(session, row.family_id)


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
