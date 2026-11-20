"""Sign-in endpoints.

``client="web"`` (default): tokens are set as httpOnly cookies and not
returned in the body. ``client="app"`` (Capacitor builds): tokens are returned
in the body for secure storage, and no cookies are set (D-011).
"""

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr

from app.api.deps import ACCESS_COOKIE, REFRESH_COOKIE, CurrentUser, MailerDep, SessionDep
from app.api.schemas import UserOut, user_out
from app.core.config import get_settings
from app.core.errors import ApiError
from app.services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["auth"])

ClientKind = Literal["web", "app"]


class MagicLinkRequest(BaseModel):
    email: EmailStr
    ref: str | None = None  # referral code from the sign-up link


class MagicLinkVerify(BaseModel):
    token: str
    client: ClientKind = "web"


class GoogleSignIn(BaseModel):
    id_token: str
    client: ClientKind = "web"
    ref: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None
    client: ClientKind = "web"


class SessionOut(BaseModel):
    user: UserOut
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int


@lru_cache
def _google_verifier() -> auth_svc.GoogleVerifier:
    return auth_svc.JwksGoogleVerifier(get_settings().google_client_ids)


def get_google_verifier() -> auth_svc.GoogleVerifier:
    return _google_verifier()


def _respond(response: Response, issued: auth_svc.IssuedSession, client: ClientKind) -> SessionOut:
    settings = get_settings()
    ttl = settings.access_token_ttl_seconds
    if client == "app":
        return SessionOut(
            user=user_out(issued.user),
            access_token=issued.access_token,
            refresh_token=issued.refresh_token,
            expires_in=ttl,
        )
    common = {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(ACCESS_COOKIE, issued.access_token, max_age=ttl, path="/", **common)  # type: ignore[arg-type]
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=issued.refresh_expires_in,
        path="/auth",
        **common,  # type: ignore[arg-type]
    )
    return SessionOut(user=user_out(issued.user), expires_in=ttl)


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth")


def _auth_error(exc: auth_svc.AuthError) -> ApiError:
    status = 403 if exc.code == "account_suspended" else 401
    return ApiError(status, exc.code, str(exc))


@router.post("/magic-link", status_code=202)
async def request_magic_link(
    body: MagicLinkRequest, request: Request, session: SessionDep, mailer: MailerDep
) -> dict[str, str]:
    """Always 202, whether or not the email has an account (no enumeration)."""
    ip = request.client.host if request.client else None
    await auth_svc.request_magic_link(session, mailer, body.email, ip, body.ref)
    return {"status": "sent"}


@router.post("/magic-link/verify")
async def verify_magic_link(
    body: MagicLinkVerify, request: Request, response: Response, session: SessionDep
) -> SessionOut:
    try:
        user = await auth_svc.verify_magic_link(session, body.token)
    except auth_svc.AuthError as exc:
        await session.rollback()
        raise _auth_error(exc) from exc
    issued = await auth_svc.issue_session(session, user, request.headers.get("user-agent"))
    await session.commit()
    return _respond(response, issued, body.client)


@router.post("/google")
async def google_sign_in(
    body: GoogleSignIn,
    request: Request,
    response: Response,
    session: SessionDep,
    verifier: Annotated[auth_svc.GoogleVerifier, Depends(get_google_verifier)],
) -> SessionOut:
    try:
        claims = verifier.verify(body.id_token)
        user = await auth_svc.sign_in_with_google(session, claims, body.ref)
    except auth_svc.AuthError as exc:
        await session.rollback()
        raise _auth_error(exc) from exc
    issued = await auth_svc.issue_session(session, user, request.headers.get("user-agent"))
    await session.commit()
    return _respond(response, issued, body.client)


@router.post("/refresh")
async def refresh(
    body: RefreshRequest, request: Request, response: Response, session: SessionDep
) -> SessionOut:
    token = body.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise ApiError(401, "invalid_session", "Please sign in again.")
    try:
        issued = await auth_svc.rotate_refresh_token(
            session, token, request.headers.get("user-agent")
        )
    except auth_svc.AuthError as exc:
        await session.commit()  # keep a reuse-triggered revocation
        _clear_cookies(response)
        raise _auth_error(exc) from exc
    await session.commit()
    return _respond(response, issued, body.client)


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: SessionDep, body: RefreshRequest | None = None
) -> None:
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if token:
        await auth_svc.revoke_token(session, token)
        await session.commit()
    _clear_cookies(response)


@router.post("/logout-all", status_code=204)
async def logout_all(user: CurrentUser, response: Response, session: SessionDep) -> None:
    """Sign out on every device."""
    await auth_svc.revoke_all_for_user(session, user.id)
    await session.commit()
    _clear_cookies(response)
