from datetime import UTC, datetime

from sqlalchemy import String, cast, delete, or_, select
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
from app.db.models.call import (
    AlertDelivery,
    Call,
    CallEpisode,
    CallSchedule,
    CareContact,
    EmergencyAlert,
    TranscriptTurn,
)
from app.db.models.call_runtime import CallExecution, CallProcessingJob, InboxEvent, OutboxMessage
from app.db.models.identity import MediaAsset, RefreshSession
from app.integrations import kakao
from app.modules.auth.service import unauthorized
from app.modules.meetings.cancellation import cancel_group_meetings, cancel_locked_meeting


def leave_meetings(session, senior_id, at):
    groups = session.scalars(
        select(Group)
        .where(Group.owner_id == senior_id, Group.status == "active")
        .order_by(Group.id)
        .with_for_update()
    )
    for group in groups:
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
    # Remove this member's applications and phone confirmations before deleting their turns.
    registrations = select(Registration.id).where(Registration.senior_id == senior_id)
    session.execute(
        delete(RegistrationAction).where(RegistrationAction.registration_id.in_(registrations))
    )
    session.execute(delete(Registration).where(Registration.senior_id == senior_id))
    session.execute(
        delete(CancellationNotice).where(CancellationNotice.recipient_senior_id == senior_id)
    )


def erase_calls(session, senior_id):
    schedules = select(CallSchedule.id).where(CallSchedule.senior_id == senior_id)
    episodes = select(CallEpisode.id).where(CallEpisode.schedule_id.in_(schedules))
    calls = select(Call.id).where(Call.episode_id.in_(episodes))
    alerts = select(EmergencyAlert.id).where(EmergencyAlert.call_id.in_(calls))
    deliveries = select(AlertDelivery.id).where(AlertDelivery.alert_id.in_(alerts))
    resources = calls.union_all(deliveries)
    # Lock the targets first so no new execution or processing job can reference them.
    session.execute(calls.order_by(Call.id).with_for_update()).all()
    session.execute(deliveries.order_by(AlertDelivery.id).with_for_update()).all()
    # Wait for callbacks holding an execution row before erasing inbox/outbox payloads.
    session.execute(
        delete(CallExecution).where(
            or_(CallExecution.call_id.in_(calls), CallExecution.delivery_id.in_(deliveries))
        )
    )
    session.execute(delete(CallProcessingJob).where(CallProcessingJob.call_id.in_(calls)))
    resource_strings = select(cast(resources.subquery().c.id, String))
    session.execute(
        delete(IdempotencyRecord).where(
            or_(
                IdempotencyRecord.subject_id == str(senior_id),
                IdempotencyRecord.subject_id.in_(resource_strings),
                IdempotencyRecord.resource_id.in_(resources),
                IdempotencyRecord.response_body["call_id"].as_string().in_(resource_strings),
                IdempotencyRecord.response_body["delivery_id"].as_string().in_(resource_strings),
            )
        )
    )
    session.execute(delete(OutboxMessage).where(OutboxMessage.resource_id.in_(resources)))
    session.execute(delete(InboxEvent).where(InboxEvent.resource_id.in_(resources)))
    session.execute(delete(TranscriptTurn).where(TranscriptTurn.call_id.in_(calls)))
    session.execute(delete(AlertDelivery).where(AlertDelivery.id.in_(deliveries)))
    session.execute(delete(EmergencyAlert).where(EmergencyAlert.id.in_(alerts)))
    session.execute(delete(Call).where(Call.episode_id.in_(episodes)))
    session.execute(delete(CallEpisode).where(CallEpisode.schedule_id.in_(schedules)))
    session.execute(delete(CallSchedule).where(CallSchedule.senior_id == senior_id))
    session.execute(delete(CareContact).where(CareContact.senior_id == senior_id))


def withdraw(session, user_id):
    # Workers can hold an execution/meeting row before requesting the member lock.
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
                    leave_meetings(session, senior.id, at)
                    erase_calls(session, senior.id)
                    senior.name = "탈퇴 회원"
                    senior.region_code = senior.phone_number = ""
                    senior.interests, senior.call_agree = [], False
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
