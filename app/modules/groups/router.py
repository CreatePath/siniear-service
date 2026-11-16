from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS
from app.core.schemas import Page
from app.modules.groups import service
from app.modules.groups.schemas import GroupCreate, GroupPatch, GroupResponse
from app.modules.meetings.schemas import MeetingCreate, MeetingResponse
from app.modules.meetings.service import create_meeting

router = APIRouter(prefix="/groups", tags=["groups"], responses=API_ERRORS)


@router.get("", response_model=Page[GroupResponse])
def listing(
    actor: Actor,
    session: Database,
    region_code: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    keyword: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    return service.list_groups(session, region_code, keyword, limit, cursor)


@router.post("", response_model=GroupResponse, status_code=201)
def create(data: GroupCreate, actor: Actor, session: Database):
    return service.create_group(session, actor, data)


@router.get("/{group_id}", response_model=GroupResponse)
def detail(group_id: UUID, actor: Actor, session: Database):
    return service.read_group(session, group_id)


@router.patch("/{group_id}", response_model=GroupResponse)
def update(group_id: UUID, data: GroupPatch, actor: Actor, session: Database):
    return service.update_group(session, actor, group_id, data)


@router.post("/{group_id}/meetings", response_model=MeetingResponse, status_code=201)
def create_schedule(group_id: UUID, data: MeetingCreate, actor: Actor, session: Database):
    return create_meeting(session, actor, data, group_id)
