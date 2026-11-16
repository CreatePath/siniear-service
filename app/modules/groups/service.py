from sqlalchemy import select

from app.core.errors import DomainError
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Group
from app.modules.groups.repository import get_group
from app.modules.groups.schemas import GroupResponse
from app.modules.meetings.cancellation import cancel_group_meetings
from app.modules.meetings.service import now, require_owner


def create_group(session, principal, data):
    with session.begin():
        group = Group(**data.model_dump(), owner_id=principal.senior_id)
        session.add(group)
        session.flush()
        return GroupResponse.model_validate(group)


def read_group(session, group_id):
    with session.begin():
        return GroupResponse.model_validate(get_group(session, group_id))


def update_group(session, principal, group_id, data):
    with session.begin():
        group = get_group(session, group_id, lock=True)
        require_owner(group.owner_id, principal)
        if group.status == "closed":
            if data.model_fields_set == {"status"}:
                return GroupResponse.model_validate(group)
            raise DomainError(409, "GROUP_CLOSED", "운영이 중단된 모임입니다.")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(group, key, value)
        if data.status == "closed":
            cancel_group_meetings(session, group.id, principal.senior_id, now())
        session.flush()
        return GroupResponse.model_validate(group)


def list_groups(session, region_code, keyword, limit, cursor):
    with session.begin():
        query = select(Group)
        if region_code:
            query = query.where(Group.region_code == region_code)
        if keyword:
            query = query.where(Group.name.icontains(keyword, autoescape=True))
        rows, next_cursor = paginate(
            session,
            query,
            column=Group.created_at,
            id_column=Group.id,
            limit=limit,
            cursor=cursor,
            descending=True,
            scope={"resource": "groups", "region_code": region_code, "keyword": keyword},
        )
        return Page(
            items=[GroupResponse.model_validate(row) for row in rows], next_cursor=next_cursor
        )
