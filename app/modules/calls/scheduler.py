from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.call import Call, CallEpisode, CallSchedule, EmergencyAlert
from app.db.models.call_runtime import OutboxMessage
from app.db.models.identity import Senior
from app.modules.calls.repository import ACTIVE, call_query, eligible
from app.modules.calls.service import next_occurrence


def pending_work(session, senior_id):
    if session.scalar(call_query(senior_id).where(Call.status.in_(ACTIVE)).limit(1)):
        return True
    return bool(
        session.scalar(
            select(EmergencyAlert.id)
            .join(Call, EmergencyAlert.call_id == Call.id)
            .join(CallEpisode, Call.episode_id == CallEpisode.id)
            .join(CallSchedule, CallEpisode.schedule_id == CallSchedule.id)
            .where(
                CallSchedule.senior_id == senior_id,
                EmergencyAlert.status.in_(["pending", "contacting"]),
            )
            .limit(1)
        )
    )


def queue_call(session, senior, episode_id, attempt, at):
    call = Call(id=uuid4(), episode_id=episode_id, attempt_no=attempt)
    session.add(call)
    session.flush()
    session.add(
        OutboxMessage(
            producer_service="C",
            operation="call.start",
            resource_id=call.id,
            dedupe_key=f"call:{call.id}",
            available_at=at,
            payload={
                "call_id": str(call.id),
                "phone_number": senior.phone_number,
                "profile": {
                    "name": senior.name,
                    "region_code": senior.region_code,
                    "interests": senior.interests,
                },
            },
        )
    )
    return call


def tick(engine, at=None):
    at = at or datetime.now(UTC)
    created = 0
    # Read candidate IDs only; every decision is repeated under the member lock.
    with Session(engine) as session:
        senior_ids = list(
            session.scalars(
                select(CallSchedule.senior_id)
                .where(CallSchedule.enabled.is_(True), CallSchedule.deleted_at.is_(None))
                .distinct()
            )
        )
    for senior_id in senior_ids:
        with Session(engine) as session, session.begin():
            senior = session.scalar(
                select(Senior).where(Senior.id == senior_id).with_for_update(key_share=True)
            )
            if not senior or not eligible(session, senior) or pending_work(session, senior_id):
                continue
            # The latest episode only: late callbacks never resurrect an older episode.
            latest = session.scalar(
                call_query(senior_id)
                .order_by(
                    func.coalesce(Call.started_at, CallEpisode.scheduled_at).desc(),
                    Call.attempt_no.desc(),
                    Call.id.desc(),
                )
                .limit(1)
            )
            if latest and latest.status == "no_answer" and latest.attempt_no == 3:
                from app.modules.emergency.service import consider_alert

                consider_alert(session, senior, latest, at)
                session.flush()
                if pending_work(session, senior_id):
                    continue
            if (
                latest
                and latest.status == "no_answer"
                and latest.attempt_no < 3
                and latest.ended_at
            ):
                schedule = session.get(
                    CallSchedule, session.get(CallEpisode, latest.episode_id).schedule_id
                )
                if schedule.enabled and schedule.deleted_at is None:
                    if latest.ended_at + timedelta(minutes=3) <= at:
                        previous = list(
                            session.scalars(
                                select(Call).where(Call.episode_id == latest.episode_id)
                            )
                        )
                        if all(c.status == "no_answer" and c.answered_at is None for c in previous):
                            queue_call(
                                session, senior, latest.episode_id, latest.attempt_no + 1, at
                            )
                            created += 1
                    # Do not let a different schedule cut short the retry interval.
                    continue
            schedule = session.scalar(
                select(CallSchedule)
                .where(
                    CallSchedule.senior_id == senior_id,
                    CallSchedule.enabled.is_(True),
                    CallSchedule.deleted_at.is_(None),
                    CallSchedule.next_call_at <= at,
                )
                .order_by(CallSchedule.next_call_at, CallSchedule.id)
                .with_for_update()
                .limit(1)
            )
            if schedule is None:
                continue
            episode = CallEpisode(
                id=uuid4(), schedule_id=schedule.id, scheduled_at=schedule.next_call_at
            )
            session.add(episode)
            session.flush()
            queue_call(session, senior, episode.id, 1, at)
            schedule.next_call_at = next_occurrence(schedule.days_of_week, schedule.local_time, at)
            created += 1
    return created
