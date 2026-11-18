from contextlib import nullcontext

from sqlalchemy import case, func, or_, select

from app.core.errors import DomainError
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Group, Meeting, Registration, Senior
from app.modules.meetings.registration_repository import registration_response
from app.modules.meetings.registration_schemas import RegistrationWithMeeting
from app.modules.meetings.repository import get_meeting
from app.modules.meetings.service import as_response, now, require_owner


def status_expression(at):
    return case(
        (Meeting.status == "canceled", "canceled"),
        (or_(Meeting.status == "completed", Meeting.ends_at <= at), "completed"),
        (or_(Meeting.status == "closed", Meeting.registration_closes_at <= at), "closed"),
        else_="recruiting",
    )


def list_meetings(session, *, group_id, region_code, from_time, to_time, status, limit, cursor):
    if from_time and to_time and from_time >= to_time:
        raise DomainError(
            422, "INVALID_TIME_RANGE", "조회 종료 시각은 시작 시각보다 늦어야 합니다."
        )
    scope = {
        "resource": "meetings",
        "group_id": group_id,
        "region_code": region_code,
        "from": from_time,
        "to": to_time,
        "status": status,
    }
    with session.begin() if not session.in_transaction() else nullcontext():
        query = select(Meeting)
        if group_id:
            query = query.where(Meeting.group_id == group_id)
        if region_code:
            query = query.where(Meeting.region_code == region_code)
        if from_time:
            query = query.where(Meeting.starts_at >= from_time)
        if to_time:
            query = query.where(Meeting.starts_at < to_time)
        if status:
            query = query.where(status_expression(now()) == status)
        rows, next_cursor = paginate(
            session,
            query,
            column=Meeting.starts_at,
            id_column=Meeting.id,
            limit=limit,
            cursor=cursor,
            scope=scope,
        )
        return Page(items=[as_response(session, row) for row in rows], next_cursor=next_cursor)


def recommendations(
    session, principal, senior_id, limit, interests=None, from_time=None, to_time=None
):
    if from_time and to_time and from_time >= to_time:
        raise DomainError(422, "INVALID_TIME_RANGE", "?? ??? ??? ???.")
    require_owner(senior_id, principal)
    with session.begin() if not session.in_transaction() else nullcontext():
        senior = session.get(Senior, senior_id)
        if senior is None:
            raise DomainError(404, "SENIOR_NOT_FOUND", "회원 정보를 찾을 수 없습니다.")
        at = now()
        count = (
            select(func.count())
            .select_from(Registration)
            .where(Registration.meeting_id == Meeting.id, Registration.status == "confirmed")
            .correlate(Meeting)
            .scalar_subquery()
        )
        already_registered = (
            select(Registration.id)
            .where(
                Registration.meeting_id == Meeting.id,
                Registration.senior_id == senior_id,
                Registration.status == "confirmed",
            )
            .exists()
        )
        score = sum(
            (
                case((Group.interests.contains([interest]), 1), else_=0)
                for interest in set(interests if interests is not None else senior.interests)
            ),
            start=0,
        )
        query = (
            select(Meeting)
            .outerjoin(Group, Group.id == Meeting.group_id)
            .where(
                Meeting.region_code == senior.region_code,
                Meeting.status == "recruiting",
                Meeting.starts_at > at,
                Meeting.registration_closes_at > at,
                or_(Meeting.group_id.is_(None), Group.status == "active"),
                count < Meeting.capacity,
                ~already_registered,
            )
        )
        if interests or senior.interests:
            query = query.order_by(score.desc())
        if from_time:
            query = query.where(Meeting.starts_at >= from_time)
        if to_time:
            query = query.where(Meeting.starts_at < to_time)
        rows = session.scalars(query.order_by(Meeting.starts_at, Meeting.id).limit(limit)).all()
        return {"items": [as_response(session, row) for row in rows]}


def list_registrations(
    session,
    principal,
    *,
    senior_id=None,
    meeting_id=None,
    status=None,
    limit=20,
    cursor=None,
    from_time=None,
    to_time=None,
):
    with session.begin() if not session.in_transaction() else nullcontext():
        if senior_id:
            require_owner(senior_id, principal)
        else:
            meeting, group = get_meeting(session, meeting_id)
            require_owner(group.owner_id if group else meeting.owner_id, principal)
        query = select(Registration)
        query = (
            query.where(Registration.senior_id == senior_id)
            if senior_id
            else query.where(Registration.meeting_id == meeting_id)
        )
        if status:
            query = query.where(Registration.status == status)
        if from_time or to_time:
            query = query.join(Meeting, Registration.meeting_id == Meeting.id)
            if from_time:
                query = query.where(Meeting.starts_at >= from_time)
            if to_time:
                query = query.where(Meeting.starts_at < to_time)
        rows, next_cursor = paginate(
            session,
            query,
            column=Registration.id,
            id_column=Registration.id,
            limit=limit,
            cursor=cursor,
            scope={
                "resource": "registrations",
                "from": from_time,
                "to": to_time,
                "actor": principal.senior_id,
                "senior_id": senior_id,
                "meeting_id": meeting_id,
                "status": status,
            },
        )
        items = []
        for row in rows:
            response = registration_response(session, row)
            if senior_id:
                response = RegistrationWithMeeting(
                    **response.model_dump(),
                    meeting=as_response(session, session.get(Meeting, row.meeting_id)),
                )
            items.append(response)
        return Page(items=items, next_cursor=next_cursor)
