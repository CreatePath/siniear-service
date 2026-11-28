from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import Actor, Cursor, Database, Key, Limit, empty_request
from app.core.errors import API_ERRORS
from app.modules.community import encouragements
from app.modules.community.encouragement_schemas import (
    EncouragementCreate,
    EncouragementWrite,
    Inbox,
    MessageView,
)
from app.modules.seniors.profile import VersionHeader

router = APIRouter(tags=["encouragements"], responses=API_ERRORS)


@router.post("/meetings/{meeting_id}/encouragements", status_code=201)
def create(
    meeting_id: UUID, data: EncouragementCreate, key: Key, actor: Actor, session: Database
) -> MessageView:
    return encouragements.create(session, actor.senior_id, meeting_id, data, key)


@router.put("/encouragements/{message_id}")
def edit(
    message_id: UUID,
    data: EncouragementWrite,
    if_match: VersionHeader,
    actor: Actor,
    session: Database,
) -> MessageView:
    return encouragements.edit(session, message_id, actor.senior_id, int(if_match[1:-1]), data)


@router.delete(
    "/encouragements/{message_id}", status_code=204, dependencies=[Depends(empty_request)]
)
def remove(message_id: UUID, actor: Actor, session: Database):
    encouragements.remove(session, message_id, actor.senior_id)
    return Response(status_code=204)


@router.get("/groups/{group_id}/me/encouragements")
def inbox(
    group_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Inbox:
    return encouragements.inbox(session, group_id, actor.senior_id, limit, cursor)


@router.post(
    "/encouragements/{message_id}/reports", status_code=204, dependencies=[Depends(empty_request)]
)
def report(message_id: UUID, actor: Actor, session: Database):
    encouragements.report(session, message_id, actor.senior_id)
    return Response(status_code=204)
