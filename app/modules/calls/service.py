from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.core.errors import DomainError
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models.call import Call, CallEpisode, CallSchedule
from app.db.models.identity import Senior
from app.modules.calls.repository import call_query, require_eligible
from app.modules.calls.schemas import CallDetail, CallResponse, ScheduleResponse
from app.modules.meetings.service import require_owner

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
SEOUL = ZoneInfo("Asia/Seoul")


def next_occurrence(days, local_time, after):
    local = after.astimezone(SEOUL)
    for delta in range(8):
        date = local.date() + timedelta(days=delta)
        candidate = datetime.combine(date, local_time, SEOUL)
        if WEEKDAYS[date.weekday()] in days and candidate > local:
            return candidate.astimezone(UTC)
    raise ValueError("No weekday")


def schedule_response(row):
    return ScheduleResponse(
        id=row.id,
        senior_id=row.senior_id,
        days_of_week=row.days_of_week,
        local_time=row.local_time.strftime("%H:%M"),
        enabled=row.enabled,
        next_call_at=row.next_call_at,
    )


def schedules(session, actor, senior_id):
    require_owner(senior_id, actor)
    with session.begin():
        return {
            "items": [
                schedule_response(row)
                for row in session.scalars(
                    select(CallSchedule)
                    .where(CallSchedule.senior_id == senior_id, CallSchedule.deleted_at.is_(None))
                    .order_by(CallSchedule.id)
                )
            ]
        }


def save_schedule(session, actor, senior_id, data, schedule_id=None, delete=False):
    require_owner(senior_id, actor)
    with session.begin():
        senior = session.scalar(
            select(Senior).where(Senior.id == senior_id).with_for_update(key_share=True)
        )
        if schedule_id:
            row = session.scalar(
                select(CallSchedule)
                .where(
                    CallSchedule.id == schedule_id,
                    CallSchedule.senior_id == senior_id,
                    CallSchedule.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                raise DomainError(404, "SCHEDULE_NOT_FOUND", "예약을 찾을 수 없습니다.")
        else:
            row = CallSchedule(senior_id=senior_id)
            session.add(row)
        if delete:
            row.enabled, row.next_call_at, row.deleted_at = False, None, datetime.now(UTC)
            return
        fields = data.model_dump(exclude_unset=True, exclude={"timezone"})
        for key, value in fields.items():
            if key == "local_time":
                value = time.fromisoformat(value)
            if key == "days_of_week":
                value = list(dict.fromkeys(value))
            setattr(row, key, value)
        if row.enabled:
            require_eligible(session, senior)
        row.next_call_at = (
            next_occurrence(row.days_of_week, row.local_time, datetime.now(UTC))
            if row.enabled
            else None
        )
        session.flush()
        return schedule_response(row)


def call_response(call, senior_id):
    duration = None
    if call.answered_at and call.ended_at:
        duration = max(0, int((call.ended_at - call.answered_at).total_seconds()))
    return CallResponse(
        senior_id=senior_id,
        duration_seconds=duration,
        **{
            name: getattr(call, name)
            for name in CallResponse.model_fields
            if name not in {"senior_id", "duration_seconds", "direction"}
        },
    )


def list_calls(session, actor, senior_id, limit, cursor, status):
    require_owner(senior_id, actor)
    with session.begin():
        query = call_query(senior_id).options(defer(Call.embedding), defer(Call.summary))
        if status:
            query = query.where(Call.status == status)
        # Started calls use actual dispatch time; queued calls use their schedule time.
        rows, following = paginate(
            session,
            query,
            column=func.coalesce(Call.started_at, CallEpisode.scheduled_at),
            id_column=Call.id,
            limit=limit,
            cursor=cursor,
            scope={"resource": "calls", "senior": senior_id, "status": status},
            descending=True,
            value_for_row=lambda row: (
                row.started_at or session.get(CallEpisode, row.episode_id).scheduled_at
            ),
        )
        return Page(items=[call_response(row, senior_id) for row in rows], next_cursor=following)


def read_call(session, actor, senior_id, call_id):
    require_owner(senior_id, actor)
    with session.begin():
        call = session.scalar(call_query(senior_id).where(Call.id == call_id))
        if call is None:
            raise DomainError(404, "CALL_NOT_FOUND", "통화를 찾을 수 없습니다.")
        return CallDetail(
            **call_response(call, senior_id).model_dump(),
            summary=(
                {"call_id": call.id, "summary": call.summary, "created_at": call.summary_created_at}
                if call.summary_status == "completed" and call.summary
                else None
            ),
        )
