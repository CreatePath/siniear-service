from sqlalchemy import func, select, update

from app.core.errors import DomainError
from app.db.models import Group
from app.db.models.interview import Card
from app.db.models.membership import JoinRequest, Membership
from app.modules.groups.schemas import GroupResponse


def get_group(session, group_id, *, lock=False):
    query = select(Group).where(Group.id == group_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    group = session.scalar(query)
    if group is None:
        raise DomainError(404, "GROUP_NOT_FOUND", "모임을 찾을 수 없습니다.")
    return group


def active_memberships(senior_id):
    return select(Membership).where(Membership.senior_id == senior_id, Membership.left_at.is_(None))


def pending(group_id, senior_id):
    return select(JoinRequest).where(
        JoinRequest.group_id == group_id,
        JoinRequest.senior_id == senior_id,
        JoinRequest.status == "pending",
    )


def group_view(session, group, senior_id):
    member = session.scalar(active_memberships(senior_id).where(Membership.group_id == group.id))
    status = "none"
    if member:
        status = "owner" if group.owner_id == senior_id else "member"
    elif session.scalar(pending(group.id, senior_id)):
        status = "pending"
    count = session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == group.id, Membership.left_at.is_(None))
    )
    return GroupResponse.model_validate(group).model_copy(
        update={
            "my_membership_status": status,
            "member_count": count,
            "badge_url": f"/api/groups/{group.id}/badge" if group.badge_id else None,
        }
    )


def issue_membership(session, group_id, senior_id, at):
    member = Membership(group_id=group_id, senior_id=senior_id, joined_at=at)
    session.add(member)
    session.flush()
    session.add(
        Card(
            senior_id=senior_id, membership_id=member.id, template_key="default", visible_fields=[]
        )
    )
    return member


def end_memberships(session, at, *, group_id=None, senior_id=None):
    if group_id is None and senior_id is None:
        raise ValueError("가입 종료 대상을 지정해 주세요.")
    periods = update(Membership).where(Membership.left_at.is_(None))
    requests = update(JoinRequest).where(JoinRequest.status == "pending")
    if group_id is not None:
        periods = periods.where(Membership.group_id == group_id)
        requests = requests.where(JoinRequest.group_id == group_id)
    if senior_id is not None:
        periods = periods.where(Membership.senior_id == senior_id)
        requests = requests.where(JoinRequest.senior_id == senior_id)
    session.execute(requests.values(status="canceled", resolved_at=at))
    session.execute(periods.values(left_at=at))
