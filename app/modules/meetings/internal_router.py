from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, Field

from app.api.dependencies import Database
from app.core.schemas import Input, Interests
from app.core.service_auth import require_service
from app.modules.meetings import phone_service, query_service

router = APIRouter(tags=["phone-tools"])
Key = Annotated[str, Header(min_length=1, max_length=200)]


class PhoneRegister(Input):
    meeting_id: UUID
    confirmation_turn_id: str = Field(min_length=1, max_length=200)


class PhoneCancel(Input):
    confirmation_turn_id: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)


class Search(Input):
    interests: Interests = []
    from_time: AwareDatetime | None = Field(default=None, alias="from")
    to_time: AwareDatetime | None = Field(default=None, alias="to")
    limit: int = Field(default=3, ge=1, le=10)


@router.post(
    "/internal/calls/{call_id}/registrations",
    dependencies=[Depends(require_service("meetings:write"))],
)
def register(call_id: UUID, data: PhoneRegister, session: Database, idempotency_key: Key):
    status, body = phone_service.register(session, call_id, data, idempotency_key)
    return JSONResponse(status_code=status, content=body)


@router.post(
    "/internal/calls/{call_id}/registrations/{registration_id}/cancel",
    dependencies=[Depends(require_service("meetings:write"))],
)
def cancel(
    call_id: UUID, registration_id: UUID, data: PhoneCancel, session: Database, idempotency_key: Key
):
    return phone_service.cancel(session, call_id, registration_id, data, idempotency_key)


@router.post(
    "/internal/calls/{call_id}/meeting-search",
    dependencies=[Depends(require_service("meetings:read"))],
)
def search(call_id: UUID, data: Search, session: Database):
    with session.begin():
        actor = phone_service.call_actor(session, call_id)
        return query_service.recommendations(
            session,
            actor,
            actor.senior_id,
            data.limit,
            interests=data.interests or None,
            from_time=data.from_time,
            to_time=data.to_time,
        )


@router.get(
    "/internal/calls/{call_id}/registrations",
    dependencies=[Depends(require_service("meetings:read"))],
)
def registrations(
    call_id: UUID,
    session: Database,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
):
    with session.begin():
        actor = phone_service.call_actor(session, call_id)
        return query_service.list_registrations(
            session,
            actor,
            senior_id=actor.senior_id,
            status=status,
            limit=limit,
            cursor=cursor,
            from_time=from_time,
            to_time=to_time,
        )
