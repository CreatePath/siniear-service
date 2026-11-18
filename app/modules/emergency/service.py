from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.core.errors import DomainError
from app.core.idempotency import fingerprint, lock_key
from app.db.models.call import AlertDelivery, Call, CallEpisode, CareContact, EmergencyAlert
from app.db.models.call_runtime import CallExecution, InboxEvent, OutboxMessage
from app.modules.calls.repository import TERMINAL, eligible, senior_for_call


def queue_next(session, senior, alert, at):
    deliveries = list(
        session.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert.id))
    )
    if any(d.status not in TERMINAL for d in deliveries):
        return
    if any(d.status == "completed" for d in deliveries):
        alert.status, alert.finished_at = "completed", at
        return
    if not eligible(session, senior):
        alert.status, alert.finished_at = "canceled", at
        return
    contact = session.scalar(
        select(CareContact)
        .where(
            CareContact.senior_id == senior.id,
            CareContact.enabled.is_(True),
            CareContact.deleted_at.is_(None),
            CareContact.phone_number.op("~")(r"^\+[1-9][0-9]{7,14}$"),
            CareContact.id.not_in([d.contact_id for d in deliveries]),
        )
        .order_by(CareContact.created_at, CareContact.id)
        .limit(1)
    )
    if len(deliveries) >= 3 or contact is None:
        alert.status, alert.finished_at = "failed", at
        alert.failure_reason = "all_contacts_failed" if deliveries else "no_available_contacts"
        return
    delivery = AlertDelivery(id=uuid4(), alert_id=alert.id, contact_id=contact.id, created_at=at)
    session.add(delivery)
    session.flush()
    alert.status = "contacting"
    session.add(
        OutboxMessage(
            producer_service="C",
            operation="emergency.start",
            resource_id=delivery.id,
            dedupe_key=f"delivery:{delivery.id}",
            available_at=at,
            payload={
                "alert_id": str(alert.id),
                "delivery_id": str(delivery.id),
                "contact_id": str(contact.id),
                "phone_number": contact.phone_number,
                "message": (
                    f"신이어 안부전화 안내입니다. 등록된 {senior.name} 님이 "
                    "안부 전화를 세 번 받지 않았습니다. 연락하여 안부를 확인해 주세요."
                ),
            },
        )
    )


def consider_alert(session, senior, call, at):
    if call.status != "no_answer" or call.attempt_no != 3:
        return
    # A newer episode or a received call prevents an older callback from starting an alert.
    from app.modules.calls.repository import call_query

    latest = session.scalar(
        call_query(senior.id)
        .order_by(
            func.coalesce(Call.started_at, CallEpisode.scheduled_at).desc(),
            Call.attempt_no.desc(),
            Call.id.desc(),
        )
        .limit(1)
    )
    if latest.id != call.id:
        return
    calls = list(
        session.scalars(
            select(Call).where(Call.episode_id == call.episode_id).order_by(Call.attempt_no)
        )
    )
    if len(calls) != 3 or any(
        c.status != "no_answer" or c.answered_at or not c.ended_at for c in calls
    ):
        return
    alert = session.scalar(select(EmergencyAlert).where(EmergencyAlert.call_id == call.id))
    if alert:
        return
    alert = EmergencyAlert(
        id=uuid4(),
        call_id=call.id,
        first_no_answer_call_id=calls[0].id,
        second_no_answer_call_id=calls[1].id,
        created_at=at,
    )
    session.add(alert)
    session.flush()
    queue_next(session, senior, alert, at)


def receive_event(session, resource_id, data, delivery=False):
    payload = data.model_dump(mode="json")
    with session.begin():
        lock_key(session, f"C:event:{data.event_id}")
        cached = session.scalar(
            select(InboxEvent).where(
                InboxEvent.consumer_service == "C", InboxEvent.event_id == data.event_id
            )
        )
        digest = fingerprint({"resource": resource_id, "payload": payload})
        if cached:
            if cached.payload_hash != digest:
                raise DomainError(409, "EVENT_CONFLICT", "이벤트 내용이 다릅니다.")
            return
        operation = "delivery.event" if delivery else "call.event"
        evidence = session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.producer_service == "T",
                OutboxMessage.resource_id == resource_id,
                OutboxMessage.operation == operation,
                OutboxMessage.dedupe_key == data.event_id,
            )
        )
        if evidence is None or evidence.payload != payload:
            raise DomainError(409, "EVENT_UNVERIFIED", "저장된 통화 이벤트와 일치하지 않습니다.")
        if delivery:
            row = session.get(AlertDelivery, resource_id)
            alert = session.get(EmergencyAlert, row.alert_id)
            senior = senior_for_call(session, alert.call_id, lock=True)
            session.refresh(alert)
            session.refresh(row)
            execution = session.scalar(
                select(CallExecution).where(CallExecution.delivery_id == resource_id)
            )
            # Read T's latest verified state. Delayed events cannot regress it.
            row.status, row.provider_call_id = execution.provider_status, execution.provider_call_id
            if row.status in TERMINAL:
                latest = session.scalar(
                    select(OutboxMessage)
                    .where(
                        OutboxMessage.producer_service == "T",
                        OutboxMessage.resource_id == resource_id,
                        OutboxMessage.operation == "delivery.event",
                        OutboxMessage.payload["status"].as_string() == row.status,
                    )
                    .order_by(OutboxMessage.available_at.desc(), OutboxMessage.id.desc())
                    .limit(1)
                )
                row.ended_at = datetime.fromisoformat(latest.payload["occurred_at"])
                if alert.status in {"pending", "contacting"}:
                    queue_next(session, senior, alert, datetime.now(UTC))
        else:
            senior = senior_for_call(session, resource_id, lock=True)
            call = session.get(Call, resource_id)
            consider_alert(session, senior, call, datetime.now(UTC))
        session.add(
            InboxEvent(
                consumer_service="C",
                event_id=data.event_id,
                resource_id=resource_id,
                payload_hash=digest,
                payload=payload,
            )
        )


def alert_response(session, alert):
    call = session.get(Call, alert.call_id)
    senior = senior_for_call(session, call.id)
    return {
        "id": alert.id,
        "senior_id": senior.id,
        "call_id": call.id,
        "episode_id": call.episode_id,
        "type": "no_response",
        "trigger_call_ids": [
            alert.first_no_answer_call_id,
            alert.second_no_answer_call_id,
            call.id,
        ],
        "consecutive_no_answer_count": 3,
        "status": alert.status,
        "created_at": alert.created_at,
        "finished_at": alert.finished_at,
    }
