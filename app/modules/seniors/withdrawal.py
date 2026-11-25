from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.db.models import (
    CancellationNotice,
    Group,
    IdempotencyRecord,
    IdentityVerification,
    Meeting,
    Registration,
    RegistrationAction,
    Senior,
    User,
)
from app.db.models.identity import MediaAsset, RefreshSession
from app.db.models.interview import Card, Interview
from app.integrations import kakao
from app.modules.auth.service import unauthorized
from app.modules.meetings.cancellation import cancel_group_meetings, cancel_locked_meeting


def leave_meetings(session, senior_id):
    from app.db.models.membership import JoinRequest, Membership
    from app.modules.groups.repository import end_memberships

    affected = (
        select(Group)
        .where(
            (Group.owner_id == senior_id)
            | Group.id.in_(
                select(JoinRequest.group_id).where(
                    JoinRequest.senior_id == senior_id, JoinRequest.status == "pending"
                )
            )
            | Group.id.in_(
                select(Membership.group_id).where(
                    Membership.senior_id == senior_id, Membership.left_at.is_(None)
                )
            )
        )
        .order_by(Group.id)
        .with_for_update()
    )
    groups = session.scalars(affected).all()
    at = datetime.now(UTC)
    end_memberships(session, at, senior_id=senior_id)
    for group in groups:
        if group.owner_id != senior_id or group.status != "active":
            continue
        end_memberships(session, at, group_id=group.id)
        group.status = "closed"
        cancel_group_meetings(session, group.id, senior_id, at)
    for meeting in session.scalars(
        select(Meeting)
        .where(
            Meeting.owner_id == senior_id,
            Meeting.ends_at > at,
            Meeting.status.not_in(["completed", "canceled"]),
        )
        .order_by(Meeting.id)
        .with_for_update()
    ):
        cancel_locked_meeting(session, meeting, senior_id, "개설자가 탈퇴했습니다.")
    registrations = select(Registration.id).where(Registration.senior_id == senior_id)
    session.execute(
        delete(RegistrationAction).where(RegistrationAction.registration_id.in_(registrations))
    )
    session.execute(delete(Registration).where(Registration.senior_id == senior_id))
    session.execute(
        delete(CancellationNotice).where(CancellationNotice.recipient_senior_id == senior_id)
    )


def withdraw(session, user_id):
    # Concurrent meeting changes can acquire locks in a different order.
    # On a PostgreSQL deadlock retry the entire transaction without intermediate effects.
    for attempt in range(3):
        try:
            with session.begin():
                user = session.get(User, user_id, with_for_update=True)
                if user is None or user.withdrawn_at:
                    raise unauthorized()
                at = datetime.now(UTC)
                senior = session.scalar(
                    select(Senior).where(Senior.user_id == user_id).with_for_update()
                )
                if senior:
                    session.execute(delete(Interview).where(Interview.senior_id == senior.id))
                    leave_meetings(session, senior.id)
                    session.execute(delete(Card).where(Card.senior_id == senior.id))
                    session.execute(
                        delete(IdempotencyRecord).where(
                            IdempotencyRecord.subject_id == str(senior.id)
                        )
                    )
                    senior.nickname = "탈퇴 회원"
                    senior.name = senior.activity_style = senior.job_title = None
                    senior.card_name_mode = "nickname"
                    senior.region_code = ""
                    senior.interests = []
                    senior.photo_id = senior.age_band = senior.experience = senior.disposition = (
                        senior.intro
                    ) = None
                    (
                        senior.strengths,
                        senior.can_share,
                        senior.want_to_learn,
                        senior.activity_goals,
                    ) = [], [], [], []
                    senior.avatar_key = "default"
                    senior.version += 1
                session.flush()
                session.execute(delete(MediaAsset).where(MediaAsset.owner_user_id == user_id))
                session.execute(delete(RefreshSession).where(RefreshSession.user_id == user_id))
                session.execute(
                    delete(IdentityVerification).where(IdentityVerification.user_id == user_id)
                )
                kakao_id = user.kakao_user_id
                user.kakao_user_id, user.withdrawn_at = None, at
                session.flush()
                if kakao_id is not None:
                    kakao.unlink(kakao_id)
            return
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) != "40P01" or attempt == 2:
                raise
