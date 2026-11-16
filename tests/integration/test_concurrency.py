from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import CancellationNotice, Group, Meeting, Registration, RegistrationAction
from app.modules.auth.dependencies import Principal
from app.modules.groups.schemas import GroupPatch
from app.modules.groups.service import update_group
from app.modules.meetings.registration_service import register
from app.modules.meetings.schemas import MeetingCreate, MeetingPatch
from app.modules.meetings.service import create_meeting as create_schedule
from app.modules.meetings.service import update_meeting
from scripts.seed_dev import ids
from tests.integration.test_groups_meetings import create_group, create_meeting, meeting_data
from tests.integration.test_registrations import signup


def race(engine, left, right):
    barrier = Barrier(2)

    def run(task):
        with Session(engine, expire_on_commit=False) as session:
            barrier.wait(timeout=5)
            try:
                return task(session)
            except DomainError as exc:
                return exc.status, exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run, [left, right]))


@pytest.mark.parametrize("change", ["close", "cancel", "capacity"])
def test_registration_races_with_manager_change(api, db_engine, change):
    meeting = create_meeting(api, capacity=2)
    assert signup(api, meeting).status_code == 201
    data = {
        "close": {"status": "closed"},
        "cancel": {"status": "canceled", "cancel_reason": "가상 사유"},
        "capacity": {"capacity": 1},
    }[change]
    results = race(
        db_engine,
        lambda session: register(session, Principal(*ids("other")), UUID(meeting["id"]), "race"),
        lambda session: update_meeting(
            session, Principal(*ids("owner")), UUID(meeting["id"]), MeetingPatch(**data)
        ),
    )
    with Session(db_engine) as session:
        row = session.get(Meeting, UUID(meeting["id"]))
        registrations = session.scalars(select(Registration)).all()
        count = sum(reg.status == "confirmed" for reg in registrations)
        assert count <= row.capacity
        if change == "cancel":
            assert row.status == "canceled"
            assert count == 0
            assert (
                session.scalar(select(func.count()).select_from(CancellationNotice))
                == len(registrations) + 1
            )
        elif change == "close":
            assert row.status == "closed"
        else:
            assert (row.capacity, count) in {(1, 1), (2, 2)}
        for reg in registrations:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RegistrationAction)
                    .where(RegistrationAction.registration_id == reg.id)
                )
                == reg.version
            )
    assert not all(isinstance(result, tuple) and result[0] == 409 for result in results)


@pytest.mark.parametrize("action", ["create", "register"])
def test_group_shutdown_races_with_activity(api, db_engine, action):
    group = create_group(api)
    data = meeting_data()
    del data["region_code"]
    meeting = api.post(f"/api/groups/{group['id']}/meetings", json=data).json()

    def activity(session):
        if action == "create":
            return create_schedule(
                session, Principal(*ids("owner")), MeetingCreate(**data), UUID(group["id"])
            )
        return register(session, Principal(*ids("member")), UUID(meeting["id"]), "race")

    race(
        db_engine,
        activity,
        lambda session: update_group(
            session, Principal(*ids("owner")), UUID(group["id"]), GroupPatch(status="closed")
        ),
    )
    with Session(db_engine) as session:
        assert session.get(Group, UUID(group["id"])).status == "closed"
        assert all(row.status == "canceled" for row in session.scalars(select(Meeting)))
        assert all(row.status == "canceled" for row in session.scalars(select(Registration)))
