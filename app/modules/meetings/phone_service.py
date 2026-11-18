from sqlalchemy import select

from app.core.errors import DomainError
from app.core.idempotency import remember, replay
from app.db.models.call import Call, TranscriptTurn
from app.db.models.registration import IdempotencyRecord, Registration, RegistrationAction
from app.modules.auth.dependencies import Principal
from app.modules.calls.repository import require_eligible, senior_for_call
from app.modules.meetings import registration_service
from app.modules.meetings.registration_repository import registration_response


def call_actor(session, call_id, active=True):
    senior = senior_for_call(session, call_id, lock=True)
    require_eligible(session, senior)
    call = session.scalar(select(Call).where(Call.id == call_id).with_for_update())
    if active and (call.status != "in_progress" or call.answered_at is None):
        raise DomainError(409, "CALL_INACTIVE", "연결 중인 통화에서만 사용할 수 있습니다.")
    return Principal(senior.user_id, senior.id)


def validate_confirmation(session, actor, phone, meeting_id, action, registration=None):
    actual = call_actor(session, phone["call_id"])
    if actual.senior_id != actor.senior_id:
        raise DomainError(403, "FORBIDDEN", "통화 회원이 다릅니다.")
    turn = session.get(TranscriptTurn, (phone["call_id"], phone["confirmation_turn_id"]))
    context = turn.action_context if turn else None
    if (
        not context
        or turn.speaker != "user"
        or context.get("action") != action
        or context.get("meeting_id") != str(meeting_id)
    ):
        raise DomainError(409, "CONFIRMATION_REQUIRED", "대상과 작업에 대한 동의가 필요합니다.")
    announcement = session.get(
        TranscriptTurn, (phone["call_id"], context.get("announcement_turn_id", ""))
    )
    # A structured server-generated announcement and a separate explicit user answer are required.
    if (
        not announcement
        or announcement.speaker != "assistant"
        or announcement.offset_ms >= turn.offset_ms
        or announcement.action_context
        != {k: v for k, v in context.items() if k != "announcement_turn_id"}
        or turn.text.strip().rstrip(".!。")
        not in {"네", "예", "동의합니다", "신청해 주세요", "취소해 주세요"}
    ):
        raise DomainError(409, "CONFIRMATION_REQUIRED", "안내 뒤의 명시적 동의를 확인해 주세요.")
    if registration and (
        context.get("registration_id") != str(registration.id)
        or context.get("expected_version") != phone["expected_version"]
    ):
        raise DomainError(409, "CONFIRMATION_REQUIRED", "취소 대상과 버전을 다시 확인해 주세요.")
    if session.scalar(
        select(RegistrationAction).where(
            RegistrationAction.call_id == phone["call_id"],
            RegistrationAction.confirmation_turn_id == phone["confirmation_turn_id"],
        )
    ):
        raise DomainError(409, "CONFIRMATION_USED", "이미 사용한 동의입니다.")
    if session.scalar(
        select(IdempotencyRecord.id).where(
            IdempotencyRecord.owner_service == "C",
            IdempotencyRecord.subject_id == str(phone["call_id"]),
            IdempotencyRecord.operation == "phone.confirmation",
            IdempotencyRecord.key == phone["confirmation_turn_id"],
        )
    ):
        raise DomainError(409, "CONFIRMATION_USED", "이미 사용한 동의입니다.")
    # Also consume a successful no-op (already registered/canceled). Otherwise an old
    # confirmation could be replayed after a later app-side status change.
    remember(
        session,
        "C",
        str(phone["call_id"]),
        "phone.confirmation",
        phone["confirmation_turn_id"],
        context,
        204,
        {},
    )


def register(session, call_id, data, key):
    with session.begin():
        actor = call_actor(session, call_id, active=False)
        return registration_service.register(
            session,
            actor,
            data.meeting_id,
            key,
            phone={"call_id": call_id, "confirmation_turn_id": data.confirmation_turn_id},
        )


def cancel(session, call_id, registration_id, data, key):
    with session.begin():
        actor = call_actor(session, call_id, active=False)
        payload = {
            "call_id": str(call_id),
            "registration_id": str(registration_id),
            **data.model_dump(),
        }
        cached = replay(session, "C", str(actor.senior_id), "phone.cancel", key, payload)
        if cached:
            return cached.response_body
        registration = session.get(Registration, registration_id)
        if not registration:
            raise DomainError(404, "REGISTRATION_NOT_FOUND", "신청을 찾을 수 없습니다.")
        if registration.senior_id != actor.senior_id:
            raise DomainError(403, "FORBIDDEN", "본인의 신청만 취소할 수 있습니다.")
        phone = {"call_id": call_id, **data.model_dump()}
        validate_confirmation(
            session, actor, phone, registration.meeting_id, "cancel", registration
        )
        registration_service.cancel_registration(
            session,
            actor,
            registration.meeting_id,
            registration.id,
            data.expected_version,
            phone=phone,
        )
        body = registration_response(session, registration).model_dump(mode="json")
        remember(session, "C", str(actor.senior_id), "phone.cancel", key, payload, 200, body)
        return body
