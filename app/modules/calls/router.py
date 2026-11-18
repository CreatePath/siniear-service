from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS
from app.core.schemas import Page
from app.modules.calls import service
from app.modules.calls.schemas import (
    CallDetail,
    CallResponse,
    CallStatus,
    ScheduleCreate,
    SchedulePatch,
    ScheduleResponse,
)

router = APIRouter(tags=["calls"], responses=API_ERRORS)
PREFIX = "/seniors/{senior_id}"


@router.get(PREFIX + "/call-schedules")
def schedules(senior_id: UUID, actor: Actor, session: Database):
    return service.schedules(session, actor, senior_id)


@router.post(PREFIX + "/call-schedules", status_code=201, response_model=ScheduleResponse)
def create(senior_id: UUID, data: ScheduleCreate, actor: Actor, session: Database):
    return service.save_schedule(session, actor, senior_id, data)


@router.patch(PREFIX + "/call-schedules/{schedule_id}", response_model=ScheduleResponse)
def update(
    senior_id: UUID, schedule_id: UUID, data: SchedulePatch, actor: Actor, session: Database
):
    return service.save_schedule(session, actor, senior_id, data, schedule_id)


@router.delete(PREFIX + "/call-schedules/{schedule_id}", status_code=204)
def delete(senior_id: UUID, schedule_id: UUID, actor: Actor, session: Database):
    service.save_schedule(session, actor, senior_id, None, schedule_id, delete=True)
    return Response(status_code=204)


@router.get(PREFIX + "/calls", response_model=Page[CallResponse])
def calls(
    senior_id: UUID,
    actor: Actor,
    session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status: CallStatus | None = None,
):
    return service.list_calls(session, actor, senior_id, limit, cursor, status)


@router.get(PREFIX + "/calls/{call_id}", response_model=CallDetail)
def detail(senior_id: UUID, call_id: UUID, actor: Actor, session: Database):
    return service.read_call(session, actor, senior_id, call_id)
