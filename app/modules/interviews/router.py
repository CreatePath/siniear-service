from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS, DomainError, ErrorResponse
from app.modules.cards.schemas import CardPreview, Confirmation, Confirmed
from app.modules.interviews import confirmation, service
from app.modules.interviews.schemas import Answer, InterviewView

router = APIRouter(prefix="/interviews", tags=["interviews"], responses=API_ERRORS)
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


async def empty_request(request: Request):
    if await request.body():
        raise DomainError(422, "VALIDATION_ERROR", "본문을 비워 주세요.")


@router.post(
    "", status_code=201, response_model_exclude_unset=True, dependencies=[Depends(empty_request)]
)
def start(actor: Actor, session: Database, key: Key) -> InterviewView:
    return service.start(session, actor, key)


@router.get("/{interview_id}", response_model_exclude_unset=True)
def read(interview_id: UUID, actor: Actor, session: Database) -> InterviewView:
    with session.begin():
        return InterviewView.model_validate(service.owned(session, actor.senior_id, interview_id))


@router.post(
    "/{interview_id}/answers",
    response_model_exclude_unset=True,
    responses={503: {"model": ErrorResponse}},
)
def answer(
    interview_id: UUID, data: Answer, actor: Actor, session: Database, key: Key
) -> InterviewView:
    return service.answer(session, actor, interview_id, data, key)


@router.post("/{interview_id}/preview")
def preview(interview_id: UUID, data: Confirmation, actor: Actor, session: Database) -> CardPreview:
    return confirmation.preview(session, actor, interview_id, data)


@router.post("/{interview_id}/confirm")
def confirm(
    interview_id: UUID, data: Confirmation, actor: Actor, session: Database, key: Key
) -> Confirmed:
    return confirmation.confirm(session, actor, interview_id, data, key)
