from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS, DomainError
from app.modules.meetings import registration_service, service
from app.modules.meetings.registration_schemas import RegistrationResponse
from app.modules.meetings.schemas import IndependentMeetingCreate, MeetingPatch, MeetingResponse

router = APIRouter(tags=["meetings"], responses=API_ERRORS)


@router.post("/meetings", response_model=MeetingResponse, status_code=201)
def create(data: IndependentMeetingCreate, actor: Actor, session: Database):
    return service.create_meeting(session, actor, data)


@router.get("/meetings/{meeting_id}", response_model=MeetingResponse)
def detail(meeting_id: UUID, actor: Actor, session: Database):
    return service.read_meeting(session, meeting_id)


@router.patch("/meetings/{meeting_id}", response_model=MeetingResponse)
def update(meeting_id: UUID, data: MeetingPatch, actor: Actor, session: Database):
    return service.update_meeting(session, actor, meeting_id, data)


@router.post(
    "/meetings/{meeting_id}/registrations",
    response_model=RegistrationResponse,
    status_code=201,
    responses={200: {"model": RegistrationResponse}},
)
async def register(
    meeting_id: UUID,
    actor: Actor,
    session: Database,
    request: Request,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
):
    # Reject arbitrary bodies instead of silently accepting identity spoofing/content changes.
    if await request.body() or not idempotency_key.strip():
        raise DomainError(422, "VALIDATION_ERROR", "신청 본문은 비워 두고 유효한 키를 보내 주세요.")
    from starlette.concurrency import run_in_threadpool

    status, body = await run_in_threadpool(
        registration_service.register, session, actor, meeting_id, idempotency_key
    )
    return JSONResponse(status_code=status, content=body)


@router.delete("/meetings/{meeting_id}/registrations/{registration_id}", status_code=204)
def cancel(
    meeting_id: UUID,
    registration_id: UUID,
    actor: Actor,
    session: Database,
    if_match: Annotated[str, Header(pattern=r'^"[1-9][0-9]*"$', max_length=12)],
):
    registration_service.cancel_registration(
        session, actor, meeting_id, registration_id, int(if_match[1:-1])
    )
    return Response(status_code=204)
