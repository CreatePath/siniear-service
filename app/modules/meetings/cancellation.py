from sqlalchemy import select

from app.db.models import CancellationNotice, Meeting, Registration
from app.modules.meetings.registration_repository import record_action


def cancel_locked_meeting(session, meeting, actor_id, reason):
    """Caller owns group/meeting locks and the encompassing transaction."""
    if meeting.status == "canceled":
        return
    meeting.status = "canceled"
    meeting.cancel_reason = reason
    registrations = session.scalars(
        select(Registration).where(
            Registration.meeting_id == meeting.id, Registration.status == "confirmed"
        )
    ).all()
    payload = {
        "meeting_id": str(meeting.id),
        "title": meeting.title,
        "starts_at": meeting.starts_at.isoformat(),
        "cancel_reason": reason,
    }
    for registration in registrations:
        registration.status = "canceled"
        registration.version += 1
        record_action(session, registration, actor_id, "cancel")
        session.add(
            CancellationNotice(
                meeting_id=meeting.id,
                recipient_senior_id=registration.senior_id,
                kind="meeting_canceled",
                payload=payload,
            )
        )
    session.add(
        CancellationNotice(
            meeting_id=meeting.id,
            recipient_senior_id=meeting.owner_id,
            kind="organizer_phone_guidance",
            payload={
                **payload,
                "message": "스마트폰을 사용하지 않는 신청자에게는 직접 전화로 취소를 알려 주세요.",
            },
        )
    )


def cancel_group_meetings(session, group_id, actor_id, at):
    meetings = session.scalars(
        select(Meeting)
        .where(Meeting.group_id == group_id)
        .order_by(Meeting.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for meeting in meetings:
        if meeting.status not in {"completed", "canceled"}:
            if meeting.ends_at <= at:
                meeting.status = "completed"
            else:
                cancel_locked_meeting(session, meeting, actor_id, "그룹 운영이 중단되었습니다.")
