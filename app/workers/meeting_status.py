"""Run explicitly: python -m app.workers.meeting_status (no automatic API scheduler)."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Meeting
from app.db.session import get_engine
from app.modules.meetings.repository import get_meeting
from app.modules.meetings.service import effective_status, now


def refresh_statuses(session):
    with session.begin():
        at = now()
        candidates = session.scalars(
            select(Meeting.id)
            .where(
                or_(
                    (Meeting.status.in_(["recruiting", "closed"])) & (Meeting.ends_at <= at),
                    (Meeting.status == "recruiting") & (Meeting.registration_closes_at <= at),
                )
            )
            .order_by(Meeting.id)
        ).all()
    counts = {"completed": 0, "closed": 0}
    for meeting_id in candidates:
        # Same lock order as API mutations; each transaction locks one meeting only.
        with session.begin():
            meeting, _ = get_meeting(session, meeting_id, lock=True)
            status = effective_status(meeting, now())
            if status != meeting.status:
                meeting.status = status
                counts[status] += 1
    return counts


if __name__ == "__main__":
    with Session(get_engine()) as session:
        print(refresh_statuses(session))
