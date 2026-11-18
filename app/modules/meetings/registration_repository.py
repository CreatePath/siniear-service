from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Meeting, Registration, RegistrationAction
from app.modules.meetings.registration_schemas import RegistrationResponse


def participant_count(session, meeting_id):
    return session.scalar(
        select(func.count())
        .select_from(Registration)
        .where(Registration.meeting_id == meeting_id, Registration.status == "confirmed")
    )


def meeting_snapshot(session, meeting_id):
    count = (
        select(func.count())
        .select_from(Registration)
        .where(Registration.meeting_id == Meeting.id, Registration.status == "confirmed")
        .correlate(Meeting)
        .scalar_subquery()
    )
    # Read capacity and participants from the same PostgreSQL statement snapshot.
    return session.execute(
        select(Meeting, count)
        .where(Meeting.id == meeting_id)
        .execution_options(populate_existing=True)
    ).one()


def registration_response(session, registration):
    first = session.get(RegistrationAction, (registration.id, 1))
    current = session.get(RegistrationAction, (registration.id, registration.version))
    return RegistrationResponse(
        id=registration.id,
        meeting_id=registration.meeting_id,
        senior_id=registration.senior_id,
        status=registration.status,
        version=registration.version,
        source="phone" if registration.call_id else "app",
        call_id=registration.call_id,
        created_at=first.created_at,
        updated_at=current.created_at,
    )


def record_action(session, registration, actor_id, action, phone=None):
    session.add(
        RegistrationAction(
            registration_id=registration.id,
            resulting_version=registration.version,
            actor_senior_id=actor_id,
            action=action,
            call_id=phone["call_id"] if phone else None,
            confirmation_turn_id=phone["confirmation_turn_id"] if phone else None,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
