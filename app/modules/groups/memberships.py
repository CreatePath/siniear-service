from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.dependencies import Actor, Cursor, Database, Key, Limit, empty_request
from app.core.errors import API_ERRORS, DomainError
from app.core.idempotency import remember, replay
from app.core.pagination import paginate
from app.core.schemas import Input, Page
from app.db.models import Group, Senior, User
from app.db.models.identity import MediaAsset
from app.db.models.interview import Card
from app.db.models.membership import JoinRequest, Membership
from app.modules.auth.dependencies import Member
from app.modules.groups.repository import (
    active_memberships,
    get_group,
    group_view,
    issue_membership,
    pending,
)
from app.modules.groups.schemas import GroupResponse
from app.modules.meetings.service import require_active, require_owner
from app.modules.seniors.photos import store_image

router = APIRouter(tags=["memberships"], responses=API_ERRORS)


class Decision(Input):
    status: Literal["approved", "rejected"]


class Application(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    senior_id: UUID
    applicant_name: str = ""
    status: Literal["pending", "approved", "rejected", "canceled"]
    created_at: datetime
    resolved_at: datetime | None


class MembershipView(BaseModel):
    id: UUID
    group_id: UUID
    senior_id: UUID
    joined_at: datetime
    card_id: UUID


def application(session, row):
    return Application.model_validate(row).model_copy(
        update={"applicant_name": session.get(Senior, row.senior_id).nickname}
    )


@router.post(
    "/groups/{group_id}/join-requests",
    status_code=201,
    responses={200: {"model": Application}},
    dependencies=[Depends(empty_request)],
)
def apply(
    group_id: UUID, actor: Actor, session: Database, key: Key, response: Response
) -> Application:
    args = ("C", str(actor.senior_id), "group.apply", key, {"group_id": group_id})
    with session.begin():
        record = replay(session, *args)
        group = get_group(session, group_id, lock=True)
        if record:
            response.status_code = record.http_status
            return application(session, session.get(JoinRequest, record.resource_id))
        require_active(group)
        if session.scalar(
            active_memberships(actor.senior_id).where(Membership.group_id == group_id)
        ):
            raise DomainError(409, "ALREADY_MEMBER", "이미 가입한 모임입니다.")
        row = session.scalar(pending(group_id, actor.senior_id))
        if row:
            response.status_code = 200
        else:
            row = JoinRequest(group_id=group_id, senior_id=actor.senior_id)
            session.add(row)
            session.flush()
            response.status_code = 201
        remember(session, *args, response.status_code, {}, resource_id=row.id)
        return application(session, row)


@router.get("/groups/{group_id}/join-requests")
def queue(
    group_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Page[Application]:
    with session.begin():
        require_owner(get_group(session, group_id).owner_id, actor)
        rows, after = paginate(
            session,
            select(JoinRequest).where(
                JoinRequest.group_id == group_id, JoinRequest.status == "pending"
            ),
            column=JoinRequest.created_at,
            id_column=JoinRequest.id,
            limit=limit,
            cursor=cursor,
            scope=["join_requests", group_id],
        )
        return Page(items=[application(session, row) for row in rows], next_cursor=after)


@router.patch("/groups/{group_id}/join-requests/{request_id}")
def review(
    group_id: UUID, request_id: UUID, data: Decision, actor: Actor, session: Database
) -> Application:
    with session.begin():
        # Withdrawal locks the applicant account before closing memberships.
        session.scalar(
            select(User.id)
            .join(Senior, Senior.user_id == User.id)
            .join(JoinRequest, JoinRequest.senior_id == Senior.id)
            .where(JoinRequest.id == request_id, JoinRequest.group_id == group_id)
            .with_for_update(of=User, read=True)
        )
        group = get_group(session, group_id, lock=True)
        require_owner(group.owner_id, actor)
        row = session.scalar(
            select(JoinRequest)
            .where(JoinRequest.id == request_id, JoinRequest.group_id == group_id)
            .with_for_update()
        )
        if row is None:
            raise DomainError(404, "REQUEST_NOT_FOUND", "가입 신청을 찾을 수 없습니다.")
        if row.status == data.status:
            return application(session, row)
        if row.status != "pending":
            raise DomainError(409, "REQUEST_RESOLVED", "이미 처리한 가입 신청입니다.")
        require_active(group)
        at = datetime.now(UTC)
        if data.status == "approved":
            row.membership_id = issue_membership(session, group_id, row.senior_id, at).id
        row.status, row.resolved_at, row.reviewed_by = data.status, at, actor.senior_id
        session.flush()
        return application(session, row)


@router.get("/me/memberships")
def mine(
    actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Page[MembershipView]:
    with session.begin():
        rows, after = paginate(
            session,
            active_memberships(actor.senior_id),
            column=Membership.joined_at,
            id_column=Membership.id,
            limit=limit,
            cursor=cursor,
            scope=["memberships", actor.senior_id],
            descending=True,
        )
        return Page(
            items=[
                MembershipView(
                    id=m.id,
                    group_id=m.group_id,
                    senior_id=m.senior_id,
                    joined_at=m.joined_at,
                    card_id=session.scalar(select(Card.id).where(Card.membership_id == m.id)),
                )
                for m in rows
            ],
            next_cursor=after,
        )


@router.delete("/groups/{group_id}/memberships/me", status_code=204)
def leave(group_id: UUID, actor: Actor, session: Database):
    with session.begin():
        group = get_group(session, group_id, lock=True)
        if group.owner_id == actor.senior_id and group.status == "active":
            raise DomainError(409, "GROUP_OWNER", "먼저 모임 운영을 종료해 주세요.")
        period = session.scalar(
            active_memberships(actor.senior_id).where(Membership.group_id == group_id)
        )
        if period:
            period.left_at = datetime.now(UTC)
        return Response(status_code=204)


class BadgeCreated(BaseModel):
    badge_id: UUID


@router.post("/group-badges", status_code=201)
def upload_badge(file: UploadFile, account: Member, session: Database) -> BadgeCreated:
    return BadgeCreated(badge_id=store_image(file, account, session, "group_badge"))


@router.get("/groups/{group_id}/badge", response_class=Response)
def read_badge(group_id: UUID, actor: Actor, session: Database):
    with session.begin():
        content = session.scalar(
            select(MediaAsset.content)
            .join(Group, Group.badge_id == MediaAsset.id)
            .where(Group.id == group_id, MediaAsset.purpose == "group_badge")
        )
        if content is None:
            raise DomainError(404, "BADGE_NOT_FOUND", "뱃지를 찾을 수 없습니다.")
        return Response(
            content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )


class Recommendation(BaseModel):
    group: GroupResponse
    reasons: list[str]


class Recommendations(BaseModel):
    items: list[Recommendation]


@router.get("/me/group-recommendations")
def recommendations(
    actor: Actor, session: Database, limit: Annotated[int, Query(ge=1, le=10)] = 3
) -> Recommendations:
    with session.begin():
        senior = session.get(Senior, actor.senior_id)
        ranked = []
        for group in session.scalars(
            select(Group)
            .where(Group.status == "active")
            .order_by(Group.created_at.desc(), Group.id)
        ):
            reasons = []
            complementary_matches = 0
            topics = set(group.interests)
            if group.region_code == senior.region_code:
                reasons.append("활동 지역이 같습니다.")
            for topic in sorted(topics.intersection(senior.interests)):
                reasons.append(f"관심사인 {topic} 활동이 있습니다.")
            for values, intent, compatible_goals in [
                (senior.can_share, "나눌 경험", ("배우", "배움", "학습")),
                (senior.want_to_learn, "배울 주제", ("나누", "나눔", "가르", "교육")),
                (senior.activity_goals, "희망 활동", ("함께", "공동")),
            ]:
                for term in dict.fromkeys(values):
                    matches = [
                        goal for goal in group.activity_goals if term in goal or goal in term
                    ]
                    complementary = next(
                        (
                            goal
                            for goal in matches
                            if any(word in goal for word in compatible_goals)
                        ),
                        None,
                    )
                    if complementary:
                        complementary_matches += 1
                        reasons.append(f"{intent}인 {term}에 맞는 모임 활동: {complementary}")
                    elif matches or term in topics:
                        reasons.append(f"{intent}인 {term} 관련 활동이 있습니다.")
            if reasons:
                ranked.append((group, reasons, complementary_matches))
        ranked.sort(key=lambda item: (item[2], len(item[1])), reverse=True)
        return Recommendations(
            items=[
                Recommendation(group=group_view(session, g, senior.id), reasons=r)
                for g, r, _ in ranked[:limit]
            ]
        )
