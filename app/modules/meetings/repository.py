from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models import Meeting
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
