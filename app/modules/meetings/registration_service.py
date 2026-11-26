import hashlib

from sqlalchemy import select

from app.core.errors import DomainError
from app.core.idempotency import lock_key
from app.db.models import IdempotencyRecord, Registration
from app.modules.groups.activity_titles import record_registration
from app.modules.meetings.registration_repository import (
    participant_count,
    record_action,
    registration_response,
)
from app.modules.meetings.repository import get_meeting, require_meeting_access
from app.modules.meetings.service import effective_status, now, require_active

OPERATION = "meeting.register"


def register(session, principal, meeting_id, key):
    with session.begin():
        subject = str(principal.senior_id)
        lock_key(session, f"C:{subject}:{OPERATION}:{key}")
        request_hash = hashlib.sha256(str(meeting_id).encode()).hexdigest()
        cached = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_service == "C",
                IdempotencyRecord.subject_id == subject,
                IdempotencyRecord.operation == OPERATION,
                IdempotencyRecord.key == key,
            )
        )
        meeting, group = get_meeting(session, meeting_id, lock=True)
        require_meeting_access(session, meeting, principal.senior_id)
        if cached:
            if cached.request_hash != request_hash:
                raise DomainError(409, "IDEMPOTENCY_CONFLICT", "같은 키의 요청 대상이 다릅니다.")
            return cached.http_status, cached.response_body
        registration = session.scalar(
            select(Registration).where(
                Registration.meeting_id == meeting_id, Registration.senior_id == principal.senior_id
            )
        )
        status = 200 if registration else 201
        if registration is None or registration.status != "confirmed":
            require_active(group)
            at = now()
            if effective_status(meeting, at) != "recruiting" or meeting.starts_at <= at:
                raise DomainError(409, "REGISTRATION_CLOSED", "신청할 수 없는 일정입니다.")
            if participant_count(session, meeting_id) >= meeting.capacity:
                raise DomainError(409, "MEETING_FULL", "모임 정원이 마감되었습니다.")
            if registration is None:
                registration = Registration(
                    meeting_id=meeting_id,
                    senior_id=principal.senior_id,
                    status="confirmed",
                    version=1,
                )
                session.add(registration)
            else:
                registration.status = "confirmed"
                registration.version += 1
            session.flush()
            record_action(session, registration, principal.senior_id, "register")
            if group:
                record_registration(session, group.id, registration)
        body = registration_response(session, registration).model_dump(mode="json")
        session.add(
            IdempotencyRecord(
                subject_id=subject,
                operation=OPERATION,
                key=key,
                request_hash=request_hash,
                http_status=status,
                response_body=body,
            )
        )
        return status, body


def cancel_registration(session, principal, meeting_id, registration_id, expected_version):
    with session.begin():
        meeting, group = get_meeting(session, meeting_id, lock=True)
        registration = session.scalar(
            select(Registration)
            .where(Registration.id == registration_id, Registration.meeting_id == meeting_id)
            .execution_options(populate_existing=True)
        )
        if registration is None:
            raise DomainError(404, "REGISTRATION_NOT_FOUND", "신청을 찾을 수 없습니다.")
        owner_id = group.owner_id if group else meeting.owner_id
        if principal.senior_id not in {registration.senior_id, owner_id}:
            raise DomainError(403, "FORBIDDEN", "신청 취소 권한이 없습니다.")
        if expected_version != registration.version:
            raise DomainError(
                409, "REGISTRATION_CHANGED", "신청이 변경되었습니다. 다시 확인해 주세요."
            )
        if registration.status == "canceled":
            return
        if meeting.starts_at <= now():
            raise DomainError(409, "CANCELLATION_CLOSED", "일정 시작 후에는 취소할 수 없습니다.")
        registration.status = "canceled"
        registration.version += 1
        record_action(session, registration, principal.senior_id, "cancel")
