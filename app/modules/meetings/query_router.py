from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS
from app.core.schemas import Page
from app.modules.meetings import query_service
from app.modules.meetings.registration_schemas import RegistrationResponse, RegistrationWithMeeting
from app.modules.meetings.schemas import MeetingResponse, MeetingStatus

router = APIRouter(tags=["meetings"], responses=API_ERRORS)
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=2048)]
RegistrationStatus = Literal["confirmed", "canceled"]


class Recommendations(BaseModel):
    items: list[MeetingResponse]


@router.get("/meetings", response_model=Page[MeetingResponse])
def listing(
    actor: Actor,
    session: Database,
    group_id: UUID | None = None,
    region_code: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    status: MeetingStatus | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    return query_service.list_meetings(
        session,
        group_id=group_id,
        region_code=region_code,
        from_time=from_time,
        to_time=to_time,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.get("/seniors/{senior_id}/meeting-recommendations", response_model=Recommendations)
def recommendations(
    senior_id: UUID, actor: Actor, session: Database, limit: Annotated[int, Query(ge=1, le=10)] = 3
):
    return query_service.recommendations(session, actor, senior_id, limit)


@router.get("/seniors/{senior_id}/registrations", response_model=Page[RegistrationWithMeeting])
def my_registrations(
    senior_id: UUID,
    actor: Actor,
    session: Database,
    status: RegistrationStatus | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    return query_service.list_registrations(
        session, actor, senior_id=senior_id, status=status, limit=limit, cursor=cursor
    )


@router.get("/meetings/{meeting_id}/registrations", response_model=Page[RegistrationResponse])
def participants(
    meeting_id: UUID,
    actor: Actor,
    session: Database,
    status: RegistrationStatus | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    return query_service.list_registrations(
        session, actor, meeting_id=meeting_id, status=status, limit=limit, cursor=cursor
    )
