import hashlib
from contextlib import nullcontext

from sqlalchemy import select, text

from app.core.errors import DomainError
from app.db.models import IdempotencyRecord, Registration
from app.modules.meetings.registration_repository import (
    participant_count,
    record_action,
    registration_response,
)
from app.modules.meetings.repository import get_meeting
from app.modules.meetings.service import effective_status, now, require_active

OPERATION = "meeting.register"


def register(session, principal, meeting_id, key, phone=None):
    operation = "phone.register" if phone else OPERATION
    with session.begin() if not session.in_transaction() else nullcontext():
        subject = str(principal.senior_id)
        digest = hashlib.sha256(f"C:{subject}:{operation}:{key}".encode()).digest()
        # Across processes: same subject/operation/key waits for the committed result.
        lock_id = int.from_bytes(digest[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        from app.core.idempotency import fingerprint

        request_hash = (
            fingerprint({"meeting_id": meeting_id, "phone": phone})
            if phone
            else hashlib.sha256(str(meeting_id).encode()).hexdigest()
        )
        cached = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_service == "C",
                IdempotencyRecord.subject_id == subject,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key == key,
            )
        )
        if cached:
            if cached.request_hash != request_hash:
                raise DomainError(409, "IDEMPOTENCY_CONFLICT", "같은 키의 요청 대상이 다릅니다.")
            return cached.http_status, cached.response_body
        if phone:
            from app.modules.meetings.phone_service import validate_confirmation

            validate_confirmation(session, principal, phone, meeting_id, "register")
        meeting, group = get_meeting(session, meeting_id, lock=True)
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
                    call_id=phone["call_id"] if phone else None,
                )
                session.add(registration)
            else:
                registration.status = "confirmed"
                registration.version += 1
            session.flush()
            record_action(session, registration, principal.senior_id, "register", phone)
        body = registration_response(session, registration).model_dump(mode="json")
        session.add(
            IdempotencyRecord(
                subject_id=subject,
                operation=operation,
                key=key,
                request_hash=request_hash,
                http_status=status,
                response_body=body,
            )
        )
        return status, body


def cancel_registration(
    session, principal, meeting_id, registration_id, expected_version, phone=None
):
    with session.begin() if not session.in_transaction() else nullcontext():
        meeting, group = get_meeting(session, meeting_id, lock=True)
        registration = session.scalar(
            select(Registration)
            .where(Registration.id == registration_id, Registration.meeting_id == meeting_id)
            .execution_options(populate_existing=True)
        )
        if registration is None:
            raise DomainError(404, "REGISTRATION_NOT_FOUND", "신청을 찾을 수 없습니다.")
        if phone and principal.senior_id != registration.senior_id:
            raise DomainError(403, "FORBIDDEN", "??? ??? ??? ? ????.")
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
        record_action(session, registration, principal.senior_id, "cancel", phone)
