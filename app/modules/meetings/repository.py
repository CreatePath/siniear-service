from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models import Meeting
from app.db.models.membership import Membership
from app.modules.groups.repository import get_group


def get_meeting(session, meeting_id, *, lock=False):
    # group_id is immutable. Lock parent first, then refresh the child after waiting.
    group_id = session.scalar(select(Meeting.group_id).where(Meeting.id == meeting_id))
    group = get_group(session, group_id, lock=lock) if group_id else None
    query = select(Meeting).where(Meeting.id == meeting_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    meeting = session.scalar(query)
    if meeting is None:
        raise DomainError(404, "MEETING_NOT_FOUND", "일정을 찾을 수 없습니다.")
    return meeting, group


def accessible_groups(senior_id):
    return select(Membership.group_id).where(
        Membership.senior_id == senior_id, Membership.left_at.is_(None)
    )


def require_meeting_access(session, meeting, senior_id):
    if meeting.group_id and not session.scalar(
        accessible_groups(senior_id).where(Membership.group_id == meeting.group_id)
    ):
        raise DomainError(403, "MEMBERSHIP_REQUIRED", "가입한 모임의 일정만 이용할 수 있습니다.")
