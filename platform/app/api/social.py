import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, MailerDep, SessionDep
from app.core.errors import ApiError
from app.models import GameTable
from app.services import social
from app.services import tables as table_svc
from app.services.game_gateway import GameGateway, get_gateway

router = APIRouter(tags=["friends & invites"])
GatewayDep = Annotated[GameGateway, Depends(get_gateway)]
Handles = Annotated[list[Annotated[str, Field(min_length=1, max_length=320)]], Field(max_length=20)]


class FriendRequestIn(BaseModel):
    handle: str = Field(min_length=1, max_length=320)  # username or email


class InviteIn(BaseModel):
    handles: Handles = Field(min_length=1)
    message: str | None = Field(default=None, max_length=500)


class OrganizeIn(BaseModel):
    tier_id: int
    title: str = Field(min_length=1, max_length=80)
    message: str | None = Field(default=None, max_length=500)
    # Omit to start as soon as the table is full.
    scheduled_start_at: datetime | None = None
    organizer_plays: bool = True
    invite: Handles = []


def _err(exc: social.SocialError | table_svc.TableError) -> ApiError:
    return ApiError(exc.status_code, exc.code, str(exc))


# ------------------------------------------------------------------ friends


@router.get("/friends")
async def friends(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    return await social.friends_overview(session, user)


@router.post("/friends/requests")
async def request_friend(
    body: FriendRequestIn, user: CurrentUser, session: SessionDep
) -> dict[str, str]:
    try:
        status = await social.request_friend(session, user, body.handle)
    except social.SocialError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return {"status": status}


@router.post("/friends/requests/{request_id}/accept", status_code=204)
async def accept_friend(request_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    try:
        await social.respond_friend(session, user, request_id, accept=True)
    except social.SocialError as exc:
        raise _err(exc) from exc
    await session.commit()


@router.post("/friends/requests/{request_id}/decline", status_code=204)
async def decline_friend(request_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    try:
        await social.respond_friend(session, user, request_id, accept=False)
    except social.SocialError as exc:
        raise _err(exc) from exc
    await session.commit()


@router.delete("/friends/{friend_id}", status_code=204)
async def remove_friend(friend_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    await social.remove_friend(session, user, friend_id)
    await session.commit()


# ------------------------------------------------------------------ invites


@router.post("/tables/{table_id}/invites")
async def invite_to_table(
    table_id: uuid.UUID, body: InviteIn, user: CurrentUser, session: SessionDep, mailer: MailerDep
) -> dict[str, Any]:
    """Invite friends (usernames or emails) to a table you're at or organized."""
    try:
        result = await social.invite(session, mailer, user, table_id, body.handles, body.message)
    except social.SocialError as exc:
        await session.rollback()
        raise _err(exc) from exc
    return {"invited": result.invited, "skipped": result.skipped}


@router.get("/tables/{table_id}/invites")
async def list_table_invites(
    table_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[dict[str, Any]]:
    """Who was invited and who answered (the organizer's RSVP list)."""
    try:
        return await social.table_invites(session, user, table_id)
    except social.SocialError as exc:
        raise _err(exc) from exc


@router.get("/invites")
async def my_invites(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    return await social.my_invites(session, user)


@router.post("/invites/{invite_id}/accept")
async def accept_invite(
    invite_id: uuid.UUID, user: CurrentUser, session: SessionDep, gateway: GatewayDep
) -> dict[str, Any]:
    try:
        table_id = await social.accept_invite(session, gateway, user, invite_id)
    except (social.SocialError, table_svc.TableError) as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    table = await session.get(GameTable, table_id)
    assert table is not None
    return await table_svc.table_view(session, table, user.id)


@router.post("/invites/{invite_id}/decline", status_code=204)
async def decline_invite(invite_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    try:
        await social.decline_invite(session, user, invite_id)
    except social.SocialError as exc:
        raise _err(exc) from exc
    await session.commit()


@router.get("/invites/code/{code}")
async def invite_preview(code: str, session: SessionDep) -> dict[str, Any]:
    """Public preview behind a shared link (works before signing in)."""
    try:
        return await social.preview_by_code(session, code)
    except social.SocialError as exc:
        raise _err(exc) from exc


# ----------------------------------------------------------- organized games


@router.post("/games/organize", status_code=201)
async def organize(
    body: OrganizeIn,
    user: CurrentUser,
    session: SessionDep,
    gateway: GatewayDep,
    mailer: MailerDep,
) -> dict[str, Any]:
    try:
        table, result = await social.organize(
            session,
            gateway,
            mailer,
            user,
            tier_id=body.tier_id,
            title=body.title,
            message=body.message,
            scheduled_start_at=body.scheduled_start_at,
            organizer_plays=body.organizer_plays,
            invitees=body.invite,
        )
    except social.SocialError as exc:
        await session.rollback()
        raise _err(exc) from exc
    return {
        "table": await table_svc.table_view(session, table, user.id),
        "invite_link": social.join_link(table),
        "invited": result.invited,
        "skipped": result.skipped,
    }


@router.post("/tables/{table_id}/cancel")
async def organizer_cancel(
    table_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """The organizer calls the game off before it starts; everyone is refunded."""
    try:
        table = await social.organizer_cancel(session, user, table_id)
    except social.SocialError as exc:
        await session.rollback()
        raise _err(exc) from exc
    await session.commit()
    return await table_svc.table_view(session, table, user.id)
