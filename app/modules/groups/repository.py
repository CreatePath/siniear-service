from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models import Group


def get_group(session, group_id, *, lock=False):
    query = select(Group).where(Group.id == group_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    group = session.scalar(query)
    if group is None:
        raise DomainError(404, "GROUP_NOT_FOUND", "모임을 찾을 수 없습니다.")
    return group
