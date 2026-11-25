from sqlalchemy import select

from app.core.errors import DomainError
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Group
from app.db.models.identity import MediaAsset
from app.modules.groups.repository import end_memberships, get_group, group_view, issue_membership
from app.modules.meetings.cancellation import cancel_group_meetings
from app.modules.meetings.service import now, require_owner


def check_badge(session, actor, badge_id):
    if badge_id and not session.scalar(
        select(MediaAsset.id).where(
            MediaAsset.id == badge_id,
            MediaAsset.owner_user_id == actor.user_id,
            MediaAsset.purpose == "group_badge",
        )
    ):
        raise DomainError(422, "VALIDATION_ERROR", "본인이 등록한 모임 뱃지를 선택해 주세요.")


def create_group(session, principal, data):
    with session.begin():
        check_badge(session, principal, data.badge_id)
        group = Group(**data.model_dump(), owner_id=principal.senior_id)
        session.add(group)
        session.flush()
        issue_membership(session, group.id, principal.senior_id, group.created_at)
        return group_view(session, group, principal.senior_id)


def read_group(session, principal, group_id):
    with session.begin():
        return group_view(session, get_group(session, group_id), principal.senior_id)


def update_group(session, principal, group_id, data):
    with session.begin():
        group = get_group(session, group_id, lock=True)
        require_owner(group.owner_id, principal)
        if group.status == "closed":
            if data.model_fields_set == {"status"}:
                return group_view(session, group, principal.senior_id)
            raise DomainError(409, "GROUP_CLOSED", "운영이 중단된 모임입니다.")
        check_badge(session, principal, data.badge_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(group, key, value)
        if data.status == "closed":
            end_memberships(session, now(), group_id=group.id)
            cancel_group_meetings(session, group.id, principal.senior_id, now())
        session.flush()
        return group_view(session, group, principal.senior_id)


def list_groups(session, principal, region_code, keyword, limit, cursor):
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
            items=[group_view(session, row, principal.senior_id) for row in rows],
            next_cursor=next_cursor,
        )
