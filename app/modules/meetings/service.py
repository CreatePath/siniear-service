from datetime import UTC, datetime

from app.core.errors import DomainError
from app.db.models import Meeting
from app.modules.groups.repository import get_group
from app.modules.meetings.cancellation import cancel_locked_meeting
from app.modules.meetings.registration_repository import meeting_snapshot, participant_count
from app.modules.meetings.repository import get_meeting, require_meeting_access
from app.modules.meetings.schemas import MeetingResponse


def now():
    return datetime.now(UTC)


def require_owner(owner_id, principal):
    if owner_id != principal.senior_id:
        raise DomainError(403, "FORBIDDEN", "관리 권한이 없습니다.")


def require_active(group):
    if group is not None and group.status != "active":
        raise DomainError(409, "GROUP_CLOSED", "운영이 중단된 모임입니다.")


def effective_status(meeting, at):
    if meeting.status == "canceled":
        return "canceled"
    if meeting.status == "completed" or meeting.ends_at <= at:
        return "completed"
    if meeting.status == "closed" or meeting.registration_closes_at <= at:
        return "closed"
    return "recruiting"


def as_response(session, meeting):
    meeting, count = meeting_snapshot(session, meeting.id)
    if count > meeting.capacity:
        raise DomainError(500, "DATA_INTEGRITY_ERROR", "일정 인원 정보를 확인할 수 없습니다.")
    return MeetingResponse.model_validate(meeting, from_attributes=True).model_copy(
        update={
            "status": effective_status(meeting, now()),
            "participant_count": count,
            "remaining_capacity": meeting.capacity - count,
        }
    )


def create_meeting(session, principal, data, group_id=None):
    with session.begin():
        values = data.model_dump(exclude={"group_id"})
        if group_id:
            group = get_group(session, group_id, lock=True)
            require_owner(group.owner_id, principal)
            require_active(group)
            values["region_code"] = group.region_code
        if data.starts_at <= now():
            raise DomainError(422, "INVALID_MEETING_TIME", "시작 시각은 미래여야 합니다.")
        meeting = Meeting(**values, group_id=group_id, owner_id=principal.senior_id)
        session.add(meeting)
        session.flush()
        return as_response(session, meeting)


def read_meeting(session, meeting_id, principal):
    with session.begin():
        meeting, _ = get_meeting(session, meeting_id)
        require_meeting_access(session, meeting, principal.senior_id)
        return as_response(session, meeting)


def update_meeting(session, principal, meeting_id, data):
    with session.begin():
        meeting, group = get_meeting(session, meeting_id, lock=True)
        require_owner(group.owner_id if group else meeting.owner_id, principal)
        at = now()
        if meeting.status == "canceled" and data.status == "canceled":
            return as_response(session, meeting)
        if effective_status(meeting, at) in {"completed", "canceled"}:
            raise DomainError(409, "MEETING_FINISHED", "종료되거나 취소된 일정입니다.")
        if data.status == "canceled":
            cancel_locked_meeting(session, meeting, principal.senior_id, data.cancel_reason)
        else:
            require_active(group)
            if meeting.starts_at <= at:
                raise DomainError(409, "MEETING_STARTED", "진행 중인 일정은 수정할 수 없습니다.")
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(meeting, key, value)
            if (
                meeting.starts_at <= at
                or meeting.ends_at <= meeting.starts_at
                or meeting.registration_closes_at > meeting.starts_at
            ):
                raise DomainError(422, "INVALID_MEETING_TIME", "일정 시각을 확인해 주세요.")
            if data.status == "recruiting" and meeting.registration_closes_at <= at:
                raise DomainError(409, "REGISTRATION_CLOSED", "신청 마감 시각이 지났습니다.")
            # Avoid autoflush until merged values are validated.
            with session.no_autoflush:
                if meeting.capacity < participant_count(session, meeting.id):
                    raise DomainError(
                        409, "CAPACITY_BELOW_PARTICIPANTS", "확정 인원보다 정원을 줄일 수 없습니다."
                    )
            meeting.status = effective_status(meeting, at)
        session.flush()
        return as_response(session, meeting)
