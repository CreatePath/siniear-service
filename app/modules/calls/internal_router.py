from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS, DomainError
from app.core.idempotency import remember, replay
from app.core.pagination import paginate
from app.core.schemas import Input, Interests
from app.core.service_auth import require_service
from app.db.models.call import AlertDelivery, Call, CallEpisode, CallSchedule, EmergencyAlert
from app.modules.calls.repository import require_eligible, senior_for_call
from app.modules.calls.schemas import StateEvent
from app.modules.emergency.service import alert_response, receive_event
from app.modules.meetings.service import require_owner

router = APIRouter(tags=["call-internal"], responses=API_ERRORS)


@router.post(
    "/internal/calls/{call_id}/events",
    status_code=204,
    dependencies=[Depends(require_service("calls:events"))],
)
def event(call_id: UUID, data: StateEvent, session: Database):
    receive_event(session, call_id, data)
    return Response(status_code=204)


@router.post(
    "/internal/alert-deliveries/{delivery_id}/events",
    status_code=204,
    dependencies=[Depends(require_service("calls:events"))],
)
def delivery_event(delivery_id: UUID, data: StateEvent, session: Database):
    receive_event(session, delivery_id, data, delivery=True)
    return Response(status_code=204)


class InterestsInput(Input):
    interests: Interests


@router.post(
    "/internal/calls/{call_id}/interests",
    dependencies=[Depends(require_service("interests:write"))],
)
def interests(
    call_id: UUID,
    data: InterestsInput,
    session: Database,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
):
    with session.begin():
        senior = senior_for_call(session, call_id, lock=True)
        require_eligible(session, senior)
        payload = {"call_id": str(call_id), **data.model_dump()}
        cached = replay(session, "C", "T", "interests", idempotency_key, payload)
        if cached:
            return cached.response_body
        senior.interests = list(dict.fromkeys(senior.interests + data.interests))[:20]
        senior.version += 1
        body = {"interests": senior.interests}
        remember(
            session, "C", "T", "interests", idempotency_key, payload, 200, body, resource_id=call_id
        )
        return body


@router.get("/seniors/{senior_id}/alerts")
def alerts(
    senior_id: UUID,
    session: Database,
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status: str | None = None,
):
    require_owner(senior_id, actor)
    with session.begin():
        query = (
            select(EmergencyAlert)
            .join(Call, EmergencyAlert.call_id == Call.id)
            .join(CallEpisode, Call.episode_id == CallEpisode.id)
            .join(CallSchedule, CallEpisode.schedule_id == CallSchedule.id)
            .where(CallSchedule.senior_id == senior_id)
        )
        if status:
            query = query.where(EmergencyAlert.status == status)
        rows, following = paginate(
            session,
            query,
            column=EmergencyAlert.created_at,
            id_column=EmergencyAlert.id,
            limit=limit,
            cursor=cursor,
            scope={"resource": "alerts", "senior": senior_id, "status": status},
            descending=True,
        )
        return {"items": [alert_response(session, row) for row in rows], "next_cursor": following}


@router.get("/internal/alerts/{alert_id}", dependencies=[Depends(require_service("alerts:read"))])
def alert_detail(alert_id: UUID, session: Database):
    with session.begin():
        alert = session.get(EmergencyAlert, alert_id)
        if alert is None:
            raise DomainError(404, "ALERT_NOT_FOUND", "사건을 찾을 수 없습니다.")
        body = alert_response(session, alert)
        body["deliveries"] = [
            {
                "id": d.id,
                "alert_id": d.alert_id,
                "contact_id": d.contact_id,
                "channel": "voice",
                "status": d.status,
                "provider_call_id": d.provider_call_id,
                "created_at": d.created_at,
                "ended_at": d.ended_at,
            }
            for d in session.scalars(
                select(AlertDelivery)
                .where(AlertDelivery.alert_id == alert_id)
                .order_by(AlertDelivery.created_at, AlertDelivery.id)
            )
        ]
        return body
